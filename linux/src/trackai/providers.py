"""Provider registry and snapshots shared by the GTK app and headless CLI."""
import fcntl
import functools
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from . import copilot, credentials
from .codex import CodexSessionScanner, codex_home, read_account
from .settings import CACHE_DIR
from .transcripts import LocalStats, TranscriptScanner
from .usage_api import ApiUsage, UsageAPIError, fetch


class ProviderSnapshot:
    def __init__(self, kind, name, config_dir, account=None, command=None):
        self.kind, self.name = kind, name
        self.command = command or kind
        self.account = account or credentials.Account(str(config_dir), True)
        self.credential_status = "missing"
        self.subscription_type = self.rate_limit_tier = None
        self.api = None
        self.api_error = None
        self.local = LocalStats()
        # Providers without a daily allowance (Codex, Copilot) get no Daily
        # row, and a "daily" icon metric falls back to their primary limit.
        self.has_daily = True
        # The limit group the overview and the "session" metric show.
        self.primary_limit, self.primary_name = "session", "Session (5h)"
        self.cost_is_estimate = False

    @property
    def id(self):
        return self.kind + ":" + self.account.id

    @property
    def label(self):
        return self.name + (" · " + self.account.email if self.account.email else "")

    def metric_percent(self, metric):
        if metric == "daily" and not self.has_daily:
            metric = "session"
        if metric in ("session", "weekly"):
            group = self.primary_limit if metric == "session" else metric
            limit = self.api.limit(group) if self.api else None
            if limit:
                return limit.percent
            return self.local.weekly_relative_percent if metric == "weekly" else None
        return self.local.daily_relative_percent if self.local.has_daily_baseline else None


class LimitCache:
    """Cross-process freshness/back-off shared by CLI and tray. No saved tokens."""
    def __init__(self, root=None, fetcher=None, clock=None, prefix="claude"):
        self.root = Path(root or CACHE_DIR)
        self.fetcher = fetcher or fetch
        self.prefix = prefix
        self.clock = clock or (lambda: datetime.now(timezone.utc).timestamp())

    def get(self, token, force=False, allow_fetch=True):
        key = hashlib.sha256(token.encode()).hexdigest()
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.root / (self.prefix + "-" + key + ".json")
        with (self.root / (self.prefix + "-" + key + ".lock")).open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                state = json.loads(path.read_text())
                if not isinstance(state, dict):
                    state = {}
                cached = ApiUsage.from_dict(state.get("usage"))
            except (OSError, ValueError, TypeError, OverflowError):
                state, cached = {}, None
            if not allow_fetch:
                return cached, state.get("error")
            now = self.clock()
            floor = 60 if force else 300
            last = state.get("attempt", 0)
            backoff = state.get("backoff", 0)
            if not isinstance(last, (int, float)) or not isinstance(backoff, (int, float)):
                state, cached, last, backoff = {}, None, 0, 0
            if now < backoff or now - last < floor or (
                    not force and cached and now - cached.fetched_at.timestamp() < 300):
                return cached, state.get("error")
            state["attempt"] = now
            try:
                cached = self.fetcher(token)
                state.update(usage=cached.to_dict(), failures=0, backoff=0, error=None)
            except UsageAPIError as err:
                state["error"] = err.description
                if err.kind == "rate_limited":
                    n = min(5, int(state.get("failures", 0)) + 1)
                    state["failures"] = n
                    state["backoff"] = now + max(min(3600, 300 * 2 ** (n - 1)), err.retry_after or 0)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(state))
            tmp.chmod(0o600)
            os.replace(tmp, path)
            return cached, state.get("error")


class ClaudeProvider:
    kind, name, command = "claude", "Claude Code", "claude"

    def __init__(self):
        self.scanners = {}
        self.cache = LimitCache()

    def scan(self, settings, force=False, offline=False):
        results = []
        for account in credentials.discover_accounts(settings.extra_config_dirs):
            snap = ProviderSnapshot(self.kind, self.name, account.config_dir, account, self.command)
            creds, snap.credential_status = credentials.load(account)
            if not Path(account.config_dir).is_dir() and creds is None:
                continue
            scanner = self.scanners.setdefault(account.id, TranscriptScanner())
            snap.local = scanner.scan(account.config_dir)
            if creds:
                snap.subscription_type = creds.subscription_type
                snap.rate_limit_tier = creds.rate_limit_tier
                try:
                    snap.api, snap.api_error = self.cache.get(
                        creds.access_token, force, allow_fetch=not creds.is_expired and not offline)
                except OSError:
                    snap.api_error = "Unable to read or write the Claude limits cache"
            results.append(snap)
        return results


class CodexProvider:
    kind, name, command = "codex", "Codex", "codex"

    def __init__(self):
        self.scanner = CodexSessionScanner()

    def scan(self, settings, force=False, offline=False):
        home = codex_home(settings.codex_home)
        if not home.is_dir():
            return []
        snap = ProviderSnapshot(self.kind, self.name, home, command=self.command)
        snap.has_daily = False
        snap.cost_is_estimate = True
        account = read_account(home)
        if account:
            snap.credential_status = "ok"
            snap.account.email = account["email"]
            snap.subscription_type = account["plan"]
        snap.local, limits = self.scanner.scan(home)
        if limits:
            snap.api, plan = limits
            snap.subscription_type = plan or snap.subscription_type
            if (datetime.now(timezone.utc) - snap.api.fetched_at).total_seconds() > 6 * 3600:
                snap.api_error = "Limits as of the last Codex run (over 6 hours old)"
        else:
            snap.api_error = "No rate-limit snapshot yet — run `codex` once"
        return [snap]


class CopilotProvider:
    kind, name, command = "copilot", "Copilot", "copilot"

    def __init__(self, cache_root=None, cli_cache=None):
        self.scanner = copilot.CopilotSessionScanner()
        self.cache_root = cache_root
        self.cli_cache = cli_cache
        self.caches = {}

    def scan(self, settings, force=False, offline=False):
        home = copilot.copilot_home()
        if not home.is_dir():
            return []
        snap = ProviderSnapshot(self.kind, self.name, home, command=self.command)
        snap.primary_limit, snap.primary_name = "monthly", "Monthly"
        snap.has_daily = False
        login = copilot.read_login(home)
        if login:
            snap.account.email = login.login
        snap.local = self.scanner.scan(home)
        stale = copilot.read_cli_cache(login, self.cli_cache)
        token = copilot.find_token(home, login)
        live = error = None
        if token:
            snap.credential_status = "ok"
            host = login.host if login else copilot.DEFAULT_HOST
            cache = self.caches.get(host)
            if cache is None:
                cache = self.caches[host] = LimitCache(
                    self.cache_root, functools.partial(copilot.fetch, host=host), prefix="copilot")
            try:
                live, error = cache.get(token, force, allow_fetch=not offline)
            except OSError:
                error = "Unable to read or write the Copilot limits cache"
        elif login:
            error = "Can't read Copilot's saved login — run `copilot login`"
        if stale and (live is None or stale.fetched_at > live.fetched_at):
            snap.api, snap.api_error = stale, "Limits as of Copilot's last start"
        else:
            snap.api, snap.api_error = live, error
        if snap.api is not None:
            snap.subscription_type = snap.api.plan
            if not snap.api.limits:
                snap.api, snap.api_error = None, "No usage limits on this Copilot plan"
        elif snap.api_error is None and not offline and not token:
            snap.api_error = "Not signed in — run `copilot login`"
        return [snap]


PROVIDERS = (ClaudeProvider, CodexProvider, CopilotProvider)


def commands_hint(joiner="or"):
    """"`claude`, `codex` or `copilot`" for setup and empty-state copy."""
    names = ["`" + p.command + "`" for p in PROVIDERS]
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " " + joiner + " " + names[-1]


def collect(providers, settings, force=False, offline=False):
    results = []
    for kind in settings.provider_order:
        provider = providers.get(kind)
        if provider is None or kind not in settings.enabled_providers:
            continue
        try:
            results.extend(provider.scan(settings, force, offline))
        except Exception as err:
            snap = ProviderSnapshot(kind, provider.name, "")
            snap.api_error = "Could not read provider data ({})".format(type(err).__name__)
            results.append(snap)
    return results
