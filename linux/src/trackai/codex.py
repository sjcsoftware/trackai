"""Read Codex auth metadata and rollout logs without any network requests."""
import base64
import json
import math
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .transcripts import TranscriptScanner, UsageEntry, parse_iso8601, _int
from .usage_api import ApiUsage, LimitInfo


def codex_home(override=""):
    return Path(override.strip() or os.environ.get("CODEX_HOME") or "~/.codex").expanduser()


def read_account(home):
    try:
        obj = json.loads((Path(home) / "auth.json").read_text())
        if not isinstance(obj, dict):
            return None
        tokens = obj.get("tokens") or {}
        if not isinstance(tokens, dict):
            tokens = {}
        claims = {}
        token = tokens.get("id_token")
        if isinstance(token, str):
            try:
                payload = token.split(".")[1]
                claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
            except (ValueError, IndexError, UnicodeError):
                pass
        if not isinstance(claims, dict):
            claims = {}
        auth = claims.get("https://api.openai.com/auth") or {}
        if not isinstance(auth, dict):
            auth = {}
        if not claims and not obj.get("OPENAI_API_KEY") and not tokens.get("account_id"):
            return None
        # JWT expiry does not invalidate the CLI login: Codex renews it.
        return {"email": claims.get("email"),
                "plan": auth.get("chatgpt_plan_type") or obj.get("auth_mode")}
    except (OSError, ValueError):
        return None


def cost(model, inp, out, cache_create, cache_read):
    """Same API-equivalent estimates as CodexPricing.swift."""
    model = model.lower()
    rates = (0.25, 2, 0.025) if "mini" in model else (
        (0.05, 0.4, 0.005) if "nano" in model else (1.25, 10, 0.125))
    return ((inp + cache_create) * rates[0] + out * rates[1] + cache_read * rates[2]) / 1_000_000


def _number(value):
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) else 0.0


def parse_limits(raw, observed):
    if not isinstance(raw, dict) or observed is None:
        return None
    limits = []
    for key, kind in (("primary", "session"), ("secondary", "weekly")):
        window = raw.get(key)
        if not isinstance(window, dict):
            continue
        minutes = _int(window.get("window_minutes"))
        name = "Session" if kind == "session" else "Weekly"
        if minutes:
            name = ("Limit ({}m)".format(minutes) if minutes < 60 else
                    "Session ({}h)".format(minutes // 60) if minutes < 1440 else
                    "Weekly" if minutes == 10080 else "Limit ({}d)".format(minutes // 1440))
        reset = None
        try:
            if isinstance(window.get("resets_at"), (int, float)):
                reset = datetime.fromtimestamp(window["resets_at"], timezone.utc)
            elif isinstance(window.get("resets_in_seconds"), (int, float)):
                reset = observed + timedelta(seconds=window["resets_in_seconds"])
        except (OverflowError, OSError, ValueError):
            pass
        limits.append(LimitInfo(kind, kind, max(0, _number(window.get("used_percent"))), reset,
                                display_name=name))
    if not limits:
        return None
    return ApiUsage(limits, None, observed), raw.get("plan_type")


class CodexSessionScanner:
    def __init__(self):
        self._cache = {}

    def scan(self, home):
        entries, live, newest = {}, set(), None
        for path in sorted((Path(home) / "sessions").rglob("*.jsonl")):
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
            records, limits = cached[1]
            for entry in records:
                if entry.key not in entries or entry.date >= entries[entry.key].date:
                    entries[entry.key] = entry
            if limits and (newest is None or limits[0].fetched_at > newest[0].fetched_at):
                newest = limits
        self._cache = {p: c for p, c in self._cache.items() if p in live}
        return TranscriptScanner()._aggregate(list(entries.values())), newest

    def _parse_file(self, path):
        records, events, newest, model, has_records = [], [], None, "unknown", False
        try:
            with path.open(encoding="utf-8", errors="replace") as stream:
                for line_no, line in enumerate(stream, 1):
                    try:
                        obj = json.loads(line)
                    except ValueError:
                        continue
                    if not isinstance(obj, dict):
                        continue
                    payload = obj.get("payload")
                    if not isinstance(payload, dict):
                        payload = {}
                    kind = obj.get("type")
                    observed = parse_iso8601(obj.get("timestamp"))
                    limits = parse_limits(payload.get("rate_limits"), observed)
                    if limits and (newest is None or limits[0].fetched_at > newest[0].fetched_at):
                        newest = limits
                    if kind in ("session_meta", "turn_context"):
                        if isinstance(payload.get("model"), str) and payload["model"]:
                            model = payload["model"]
                        continue
                    if kind == "token_usage_record":
                        # Presence, even with zero/malformed usage, suppresses old events.
                        has_records = True
                        usage = payload.get("usage")
                        key = "codex:rec:" + str(payload.get("response_id") or "{}:{}".format(path.stem, line_no))
                        target = records
                    elif kind == "event_msg" and payload.get("type") == "token_count":
                        info = payload.get("info")
                        usage = info.get("last_token_usage") if isinstance(info, dict) else None
                        key = "codex:evt:{}:{}".format(path.stem, line_no)
                        target = events
                    else:
                        continue
                    if not isinstance(usage, dict) or observed is None:
                        continue
                    raw = _int(usage.get("input_tokens"))
                    cached = min(raw, _int(usage.get("cached_input_tokens")))
                    write = min(raw - cached, _int(usage.get("cache_write_input_tokens")))
                    inp = max(0, raw - cached - write)
                    out = _int(usage.get("output_tokens"))
                    if inp + out + cached + write:
                        target.append(UsageEntry(key, model, observed, inp, out, write, cached,
                                                 cost(model, inp, out, write, cached)))
        except OSError:
            pass
        return (records if has_records else events), newest
