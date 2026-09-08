"""Claude Code account and login discovery (port of Credentials.swift).

On Linux, Claude Code keeps its OAuth token in ``<config dir>/.credentials.json``.
Some desktops instead hand it to the Secret Service (gnome-keyring / KWallet),
so ``secret-tool`` is used as a read-only fallback — the Linux counterpart of
the macOS Keychain lookup. trackai only ever reads; Claude Code stays
fully in charge of the login.
"""

from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone

KEYCHAIN_SERVICE = "Claude Code-credentials"

STATUS_OK = "ok"
STATUS_EXPIRED = "expired"
STATUS_MISSING = "missing"

STATUS_TEXT = {
    STATUS_OK: "ok",
    STATUS_EXPIRED: "expired — run `claude` in a terminal to refresh",
    STATUS_MISSING: "not found — run `claude` in a terminal and log in",
}


class OAuthCredentials(object):
    __slots__ = ("access_token", "expires_at", "subscription_type", "rate_limit_tier")

    def __init__(self, access_token, expires_at, subscription_type, rate_limit_tier):
        self.access_token = access_token
        self.expires_at = expires_at
        self.subscription_type = subscription_type
        self.rate_limit_tier = rate_limit_tier

    @property
    def is_expired(self):
        if self.expires_at is None:
            return False
        return (self.expires_at - datetime.now(timezone.utc)).total_seconds() < 60


class Account(object):
    __slots__ = ("id", "config_dir", "is_default", "email", "organization_name")

    def __init__(self, config_dir, is_default):
        self.id = config_dir
        self.config_dir = config_dir
        self.is_default = is_default
        self.email = None
        self.organization_name = None

    @property
    def label(self):
        if self.email:
            return self.email
        return os.path.basename(self.config_dir.rstrip(os.sep)) or self.config_dir

    def __eq__(self, other):
        return isinstance(other, Account) and other.id == self.id

    def __hash__(self):
        return hash(self.id)


def default_config_dir():
    # type: () -> str
    """Default Claude Code config dir (~/.claude, or $CLAUDE_CONFIG_DIR if set)."""
    env = os.environ.get("CLAUDE_CONFIG_DIR", "")
    if env:
        return os.path.abspath(os.path.expanduser(env))
    return os.path.join(os.path.expanduser("~"), ".claude")


def discover_accounts(extra_config_dirs):
    # type: (list) -> list
    """Discover accounts: the default one plus any extra config dirs from settings."""
    accounts = []
    seen = set()

    def add(path, is_default):
        path = os.path.abspath(os.path.expanduser(path))
        if path in seen:
            return
        seen.add(path)
        account = Account(path, is_default)
        account.email, account.organization_name = read_account_info(path)
        accounts.append(account)

    add(default_config_dir(), True)
    for raw in extra_config_dirs or []:
        expanded = os.path.abspath(os.path.expanduser(str(raw)))
        if os.path.isdir(expanded):
            add(expanded, False)
    return accounts


def read_account_info(config_dir):
    # type: (str) -> tuple
    """Read email/org from the account's claude.json.

    ``~/.claude.json`` for the default config dir, ``<dir>/.claude.json`` for
    custom ones.
    """
    candidates = [os.path.join(config_dir, ".claude.json")]
    home = os.path.expanduser("~")
    if os.path.abspath(config_dir) == os.path.join(home, ".claude"):
        candidates.append(os.path.join(home, ".claude.json"))
    for path in candidates:
        try:
            with open(path, "r", encoding="utf-8") as fh:
                obj = json.load(fh)
        except (OSError, ValueError):
            continue
        if not isinstance(obj, dict):
            continue
        oauth = obj.get("oauthAccount")
        if not isinstance(oauth, dict):
            continue
        email = oauth.get("emailAddress")
        org = oauth.get("organizationName")
        return (email if isinstance(email, str) else None,
                org if isinstance(org, str) else None)
    return (None, None)


def load(account):
    # type: (Account) -> tuple
    """Resolve credentials for an account: file first, then the Secret Service."""
    creds = read_credentials_file(account.config_dir)
    if creds is not None:
        return (creds, STATUS_EXPIRED if creds.is_expired else STATUS_OK)
    if account.is_default:
        creds = read_secret_service()
        if creds is not None:
            return (creds, STATUS_EXPIRED if creds.is_expired else STATUS_OK)
    return (None, STATUS_MISSING)


def read_credentials_file(config_dir):
    # type: (str) -> "OAuthCredentials | None"
    path = os.path.join(config_dir, ".credentials.json")
    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except OSError:
        return None
    return parse_credentials(data)


def read_secret_service():
    # type: () -> "OAuthCredentials | None"
    """Read the token from gnome-keyring/KWallet via `secret-tool`, if present."""
    queries = [
        ["service", KEYCHAIN_SERVICE],
        ["service", "Claude Code", "account", "credentials"],
    ]
    for attrs in queries:
        try:
            proc = subprocess.run(
                ["secret-tool", "lookup"] + attrs,
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=10,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        if proc.returncode == 0 and proc.stdout.strip():
            creds = parse_credentials(proc.stdout)
            if creds is not None:
                return creds
    return None


def parse_credentials(data):
    # type: (bytes) -> "OAuthCredentials | None"
    try:
        obj = json.loads(data.decode("utf-8"))
    except (ValueError, UnicodeDecodeError, AttributeError):
        return None
    if not isinstance(obj, dict):
        return None
    oauth = obj.get("claudeAiOauth")
    if not isinstance(oauth, dict):
        oauth = obj
    token = oauth.get("accessToken")
    if not isinstance(token, str) or not token:
        return None
    expires = None
    ms = oauth.get("expiresAt")
    if isinstance(ms, (int, float)) and not isinstance(ms, bool):
        try:
            expires = datetime.fromtimestamp(ms / 1000.0, timezone.utc)
        except (OverflowError, OSError, ValueError):
            expires = None
    sub = oauth.get("subscriptionType")
    tier = oauth.get("rateLimitTier")
    return OAuthCredentials(
        access_token=token,
        expires_at=expires,
        subscription_type=sub if isinstance(sub, str) else None,
        rate_limit_tier=tier if isinstance(tier, str) else None,
    )
