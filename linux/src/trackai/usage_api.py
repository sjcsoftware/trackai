"""Anthropic plan-limit lookups (port of UsageAPI.swift).

The only network call trackai ever makes: a read-only GET against the
endpoint Claude Code itself uses, authenticated with the OAuth token Claude
Code already stores. The token is never refreshed or rewritten here.
"""

from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request
from datetime import datetime, timezone

from .transcripts import parse_iso8601

ENDPOINT = "https://api.anthropic.com/api/oauth/usage"
TIMEOUT = 20.0


class LimitInfo(object):
    __slots__ = ("kind", "group", "percent", "resets_at", "is_active", "_display_name")

    def __init__(self, kind, group, percent, resets_at, is_active=True, display_name=None):
        self._display_name = display_name
        self.kind = kind
        self.group = group
        self.percent = percent
        self.resets_at = resets_at
        self.is_active = is_active

    @property
    def id(self):
        return self.kind

    @property
    def display_name(self):
        if self._display_name:
            return self._display_name
        names = {
            "session": "Session (5h)",
            "weekly_all": "Weekly (all models)",
            "weekly_opus": "Weekly (Opus)",
            "weekly_sonnet": "Weekly (Sonnet)",
        }
        if self.kind in names:
            return names[self.kind]
        return " ".join(p[:1].upper() + p[1:] for p in self.kind.split("_") if p)


class ApiUsage(object):
    __slots__ = ("limits", "extra_credits_used", "fetched_at")

    def __init__(self, limits, extra_credits_used, fetched_at):
        self.limits = limits
        self.extra_credits_used = extra_credits_used   # USD
        self.fetched_at = fetched_at

    def limit(self, group):
        # type: (str) -> "LimitInfo | None"
        for l in self.limits:
            if l.group == group:
                return l
        return None

    # Persisted to disk so restarts/updates keep the last good data instead of
    # immediately re-hitting the rate-limited endpoint.
    def to_dict(self):
        d = {
            "fetchedAt": self.fetched_at.timestamp(),
            "limits": [],
        }
        for l in self.limits:
            entry = {
                "kind": l.kind,
                "group": l.group,
                "percent": l.percent,
                "isActive": l.is_active,
            }
            if l.resets_at is not None:
                entry["resetsAt"] = l.resets_at.timestamp()
            d["limits"].append(entry)
        if self.extra_credits_used is not None:
            d["extraCreditsUsed"] = self.extra_credits_used
        return d

    @staticmethod
    def from_dict(d):
        # type: (dict) -> "ApiUsage | None"
        if not isinstance(d, dict):
            return None
        ts = d.get("fetchedAt")
        raw_limits = d.get("limits")
        if not isinstance(ts, (int, float)) or not isinstance(raw_limits, list):
            return None
        limits = []
        for e in raw_limits:
            if not isinstance(e, dict) or not isinstance(e.get("kind"), str):
                continue
            resets = e.get("resetsAt")
            limits.append(LimitInfo(
                kind=e["kind"],
                group=e.get("group") or e["kind"],
                percent=float(e.get("percent") or 0),
                resets_at=(datetime.fromtimestamp(resets, timezone.utc)
                           if isinstance(resets, (int, float)) else None),
                is_active=bool(e.get("isActive", True)),
            ))
        extra = d.get("extraCreditsUsed")
        return ApiUsage(
            limits=limits,
            extra_credits_used=float(extra) if isinstance(extra, (int, float)) else None,
            fetched_at=datetime.fromtimestamp(ts, timezone.utc),
        )


class UsageAPIError(Exception):
    """A failed usage lookup, carrying enough detail to drive the backoff."""

    def __init__(self, kind, code=None, retry_after=None, message=None):
        Exception.__init__(self, message or kind)
        self.kind = kind              # "http" | "rate_limited" | "network" | "bad_response"
        self.code = code
        self.retry_after = retry_after
        self.message = message

    @property
    def description(self):
        if self.kind == "http":
            if self.code == 401:
                return "unauthorized (token expired?)"
            return "HTTP {}".format(self.code)
        if self.kind == "rate_limited":
            return "rate limited — retrying soon"
        if self.kind == "network":
            return self.message or "network error"
        return "unexpected response"

    def __str__(self):
        return self.description


def fetch(token):
    # type: (str) -> ApiUsage
    """Fetch plan limits. Raises UsageAPIError. Blocking; call off the UI thread."""
    req = urllib.request.Request(ENDPOINT, method="GET")
    req.add_header("Authorization", "Bearer {}".format(token))
    req.add_header("anthropic-beta", "oauth-2025-04-20")
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", "trackai-linux")

    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            body = resp.read()
    except urllib.error.HTTPError as err:
        if err.code == 429:
            retry_after = None
            raw = err.headers.get("Retry-After") if err.headers else None
            try:
                retry_after = float(raw) if raw else None
            except (TypeError, ValueError):
                retry_after = None
            raise UsageAPIError("rate_limited", code=429, retry_after=retry_after)
        raise UsageAPIError("http", code=err.code)
    except urllib.error.URLError as err:
        raise UsageAPIError("network", message=str(getattr(err, "reason", err)))
    except (socket.timeout, OSError) as err:
        raise UsageAPIError("network", message=str(err))

    usage = parse(body)
    if usage is None:
        raise UsageAPIError("bad_response")
    return usage


def parse(data):
    # type: (bytes) -> "ApiUsage | None"
    try:
        obj = json.loads(data.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(obj, dict):
        return None

    limits = []
    raw = obj.get("limits")
    if isinstance(raw, list):
        for entry in raw:
            if not isinstance(entry, dict) or not isinstance(entry.get("kind"), str):
                continue
            limits.append(LimitInfo(
                kind=entry["kind"],
                group=entry.get("group") or entry["kind"],
                percent=_number(entry.get("percent")),
                resets_at=parse_iso8601(entry.get("resets_at") or ""),
                is_active=bool(entry.get("is_active", True)),
            ))

    # Fallback for schema drift: derive from five_hour / seven_day objects.
    if not limits:
        mapping = [
            ("five_hour", "session"),
            ("seven_day", "weekly_all"),
            ("seven_day_opus", "weekly_opus"),
            ("seven_day_sonnet", "weekly_sonnet"),
        ]
        for key, kind in mapping:
            entry = obj.get(key)
            if not isinstance(entry, dict):
                continue
            limits.append(LimitInfo(
                kind=kind,
                group="weekly" if kind == "weekly_all" else kind,
                percent=_number(entry.get("utilization")),
                resets_at=parse_iso8601(entry.get("resets_at") or ""),
                is_active=True,
            ))

    extra_credits = None
    extra = obj.get("extra_usage")
    if isinstance(extra, dict):
        used = extra.get("used_credits")
        if isinstance(used, (int, float)) and used > 0:
            places = extra.get("decimal_places")
            places = places if isinstance(places, int) else 2
            extra_credits = used / (10.0 ** places)

    return ApiUsage(limits=limits, extra_credits_used=extra_credits,
                    fetched_at=datetime.now(timezone.utc))


def _number(value):
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    return 0.0
