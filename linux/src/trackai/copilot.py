"""GitHub Copilot CLI: login discovery, monthly quota and local session logs.

Copilot CLI keeps its state in ``$COPILOT_HOME`` (``~/.copilot``). Every model
call is logged as a ``session.usage_record`` event in
``session-state/<id>/events.jsonl``, with exact per-type token counts and the
AI credits it cost. The plan quota comes from the read-only endpoint the CLI
itself calls, authenticated with the OAuth token the CLI already stores in the
Secret Service (or, without a keyring, in its config file). Nothing is ever
written back.
"""
import json
import math
import os
import re
import socket
import subprocess
import urllib.error
import urllib.request
from collections import namedtuple
from datetime import datetime, timezone
from pathlib import Path

from .transcripts import TranscriptScanner, UsageEntry, parse_iso8601, _int
from .usage_api import ApiUsage, LimitInfo, UsageAPIError

KEYRING_SERVICE = "copilot-cli"
DEFAULT_HOST = "https://github.com"
TIMEOUT = 20.0
# GitHub bills Copilot in AI credits; 1 AI credit = $0.01.
USD_PER_AI_CREDIT = 0.01

Login = namedtuple("Login", "host login")


def copilot_home():
    return Path(os.environ.get("COPILOT_HOME") or "~/.copilot").expanduser()


def read_jsonc(path):
    """Copilot's JSON files start with ``//`` comment lines."""
    try:
        text = Path(path).read_text(encoding="utf-8")
        obj = json.loads(re.sub(r"^\s*//.*$", "", text, flags=re.M))
    except (OSError, ValueError, UnicodeDecodeError):
        return {}
    return obj if isinstance(obj, dict) else {}


def read_login(home):
    """The account Copilot CLI last signed in with, or None."""
    config = read_jsonc(Path(home) / "config.json")
    user = config.get("lastLoggedInUser") or config.get("last_logged_in_user")
    if not isinstance(user, dict) or not isinstance(user.get("login"), str) or not user["login"]:
        return None
    host = user.get("host") if isinstance(user.get("host"), str) and user.get("host") else DEFAULT_HOST
    return Login(host.rstrip("/"), user["login"])


def api_base(host):
    hostname = re.sub(r"^https?://", "", host or DEFAULT_HOST).strip("/")
    if hostname == "github.com":
        return "https://api.github.com"
    if hostname.endswith(".ghe.com"):
        return "https://api." + hostname
    return "https://" + hostname + "/api/v3"


def _secret_tool(attrs):
    try:
        proc = subprocess.run(["secret-tool", "lookup"] + attrs, stdout=subprocess.PIPE,
                              stderr=subprocess.DEVNULL, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    token = proc.stdout.decode("utf-8", "replace").strip() if proc.returncode == 0 else ""
    return token or None


def _libsecret(attrs):
    """libsecret through GObject introspection, for desktops without secret-tool."""
    try:
        import gi
        gi.require_version("Secret", "1")
        from gi.repository import Secret
        schema = Secret.Schema.new("org.freedesktop.Secret.Generic", Secret.SchemaFlags.DONT_MATCH_NAME,
                                   {key: Secret.SchemaAttributeType.STRING for key in attrs})
        token = Secret.password_lookup_sync(schema, attrs, None)
    except Exception:      # missing typelib, no Secret Service, locked keyring
        return None
    return token.strip() if isinstance(token, str) and token.strip() else None


def _gh_token(host):
    hostname = re.sub(r"^https?://", "", host).strip("/")
    try:
        proc = subprocess.run(["gh", "auth", "token", "--hostname", hostname], stdout=subprocess.PIPE,
                              stderr=subprocess.DEVNULL, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    token = proc.stdout.decode("utf-8", "replace").strip() if proc.returncode == 0 else ""
    return token or None


def find_token(home, login):
    """Copilot CLI's own token, in the CLI's order; read-only, never pasted."""
    token = os.environ.get("COPILOT_GITHUB_TOKEN", "").strip()
    if token:
        return token
    if login is not None:
        account = login.host + ":" + login.login
        # Without a keyring the CLI keeps {"<host>:<login>": token} in config.json.
        for value in read_jsonc(Path(home) / "config.json").values():
            if isinstance(value, dict) and isinstance(value.get(account), str) and value[account]:
                return value[account]
        attrs = {"service": KEYRING_SERVICE, "account": account}
        token = _secret_tool(["service", KEYRING_SERVICE, "account", account]) or _libsecret(attrs)
        if token:
            return token
    return _gh_token(login.host if login else DEFAULT_HOST)


def _number(value):
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) \
        and math.isfinite(value) else None


def _reset_date(obj):
    reset = parse_iso8601(obj.get("quota_reset_date_utc"))
    if reset is None and isinstance(obj.get("quota_reset_date"), str):
        try:
            reset = datetime.strptime(obj["quota_reset_date"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return reset


def parse_user(obj, fetched_at):
    """ApiUsage from a ``copilot_internal/user`` response; unlimited quotas are skipped."""
    if not isinstance(obj, dict) or not isinstance(obj.get("quota_snapshots"), dict):
        return None
    snapshots = obj["quota_snapshots"]
    credits = bool(obj.get("token_based_billing"))
    reset = _reset_date(obj)
    limits = []
    for key, group, name in (("premium_interactions", "monthly", "AI credits" if credits else "Premium requests"),
                             ("chat", "chat", "Chat"), ("completions", "completions", "Completions")):
        quota = snapshots.get(key)
        if not isinstance(quota, dict) or quota.get("unlimited") is True:
            continue
        entitlement = _number(quota.get("entitlement")) or 0.0
        remaining = _number(quota.get("percent_remaining"))
        used = _number(quota.get("credits_used")) if credits and key == "premium_interactions" else None
        if used is None and entitlement > 0:
            left = _number(quota.get("quota_remaining"))
            left = _number(quota.get("remaining")) if left is None else left
            used = max(0.0, entitlement - left) if left is not None else None
        if remaining is not None:
            percent = max(0.0, 100.0 - remaining)
        elif used is not None and entitlement > 0:
            percent = used / entitlement * 100.0
        else:
            continue
        detail = "{:,.0f} / {:,.0f}".format(used, entitlement) if used is not None and entitlement > 0 else None
        limits.append(LimitInfo(group, group, percent, reset, display_name=name + " (monthly)", detail=detail))
    plan = obj.get("copilot_plan") if isinstance(obj.get("copilot_plan"), str) else None
    return ApiUsage(limits, None, fetched_at, plan)


def fetch(token, host=DEFAULT_HOST):
    """Live quota for this login. Raises UsageAPIError. Blocking; call off the UI thread."""
    req = urllib.request.Request(api_base(host) + "/copilot_internal/user", method="GET")
    req.add_header("Authorization", "token " + token)
    req.add_header("Accept", "application/json")
    req.add_header("User-Agent", "trackai-linux")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            body = resp.read()
    except urllib.error.HTTPError as err:
        if err.code == 429 or (err.code == 403 and err.headers and err.headers.get("Retry-After")):
            try:
                retry_after = float(err.headers.get("Retry-After")) if err.headers else None
            except (TypeError, ValueError):
                retry_after = None
            raise UsageAPIError("rate_limited", code=err.code, retry_after=retry_after)
        raise UsageAPIError("http", code=err.code)
    except urllib.error.URLError as err:
        raise UsageAPIError("network", message=str(getattr(err, "reason", err)))
    except (socket.timeout, OSError) as err:
        raise UsageAPIError("network", message=str(err))
    try:
        usage = parse_user(json.loads(body.decode("utf-8")), datetime.now(timezone.utc))
    except (ValueError, UnicodeDecodeError):
        usage = None
    if usage is None:
        raise UsageAPIError("bad_response")
    return usage


def cli_cache_path():
    base = os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
    return Path(base) / "copilot" / "copilot-user-cache.json"


def read_cli_cache(login, path=None):
    """The quota response Copilot CLI cached when it last started, or None."""
    entries = read_jsonc(path or cli_cache_path()).get("copilotUserCache")
    best = None
    for entry in (entries.values() if isinstance(entries, dict) else ()):
        if not isinstance(entry, dict) or not isinstance(entry.get("response"), dict):
            continue
        response = entry["response"]
        if login is not None and response.get("login") != login.login:
            continue
        retrieved = parse_iso8601(entry.get("retrievedAt"))
        usage = parse_user(response, retrieved) if retrieved else None
        if usage is not None and (best is None or usage.fetched_at > best.fetched_at):
            best = usage
    return best


def _token_counts(usage):
    copilot_usage = usage.get("copilotUsage")
    details = copilot_usage.get("tokenDetails") if isinstance(copilot_usage, dict) else None
    if isinstance(details, list) and details:
        counts = {}
        for item in details:
            if isinstance(item, dict) and isinstance(item.get("tokenType"), str):
                counts[item["tokenType"]] = counts.get(item["tokenType"], 0) + _int(item.get("tokenCount"))
        return (counts.get("input", 0), counts.get("output", 0),
                counts.get("cache_write", 0), counts.get("cache_read", 0))
    # inputTokens includes cached reads and writes.
    read, write = _int(usage.get("cacheReadTokens")), _int(usage.get("cacheWriteTokens"))
    return (max(0, _int(usage.get("inputTokens")) - read - write), _int(usage.get("outputTokens")), write, read)


def _credits(usage):
    copilot_usage = usage.get("copilotUsage")
    if not isinstance(copilot_usage, dict):
        return 0.0
    nano = _number(copilot_usage.get("totalNanoAiu"))
    if nano is None:
        nano = 0.0
        for item in copilot_usage.get("tokenDetails") or ():
            if isinstance(item, dict) and _number(item.get("batchSize")):
                nano += _int(item.get("tokenCount")) * (_number(item.get("costPerBatch")) or 0) / item["batchSize"]
    return max(0.0, nano) / 1e9


class CopilotSessionScanner:
    def __init__(self):
        self._cache = {}

    def scan(self, home):
        entries, live = {}, set()
        for path in sorted((Path(home) / "session-state").glob("*/events.jsonl")):
            try:
                st = path.stat()
            except OSError:
                continue
            live.add(path)
            fingerprint = (st.st_mtime_ns, st.st_size)
            cached = self._cache.get(path)
            if cached is None or cached[0] != fingerprint:
                cached = (fingerprint, self._parse_file(path))
                self._cache[path] = cached
            for entry in cached[1]:
                if entry.key not in entries or entry.date >= entries[entry.key].date:
                    entries[entry.key] = entry
        self._cache = {p: c for p, c in self._cache.items() if p in live}
        return TranscriptScanner()._aggregate(list(entries.values()))

    def _parse_file(self, path):
        records = {}
        try:
            with path.open(encoding="utf-8", errors="replace") as stream:
                for line_no, line in enumerate(stream, 1):
                    if '"session.usage_record"' not in line:
                        continue
                    try:
                        obj = json.loads(line)
                    except ValueError:
                        continue
                    if not isinstance(obj, dict) or obj.get("type") != "session.usage_record":
                        continue
                    data = obj.get("data")
                    usage = data.get("usage") if isinstance(data, dict) else None
                    date = parse_iso8601(obj.get("timestamp"))
                    if not isinstance(usage, dict) or date is None:
                        continue
                    model = usage.get("model") or usage.get("responseModel")
                    model = model if isinstance(model, str) and model else "unknown"
                    inp, out, write, read = _token_counts(usage)
                    if not inp + out + write + read:
                        continue
                    accounting = usage.get("accounting") if isinstance(usage.get("accounting"), dict) else {}
                    ident = accounting.get("usageId") or usage.get("apiCallId") or obj.get("id") or \
                        "{}:{}".format(path.parent.name, line_no)
                    key = "copilot:" + str(ident)
                    records[key] = UsageEntry(key, model, date, inp, out, write, read,
                                              _credits(usage) * USD_PER_AI_CREDIT)
        except OSError:
            pass
        return list(records.values())
