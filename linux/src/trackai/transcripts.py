"""Local token accounting from Claude Code transcripts (port of Transcripts.swift).

Claude Code writes one JSONL file per session under ``<config dir>/projects``.
Every assistant record carries a ``usage`` object; summing those gives exact
local token counts without talking to any server.
"""

from __future__ import annotations

import json
import math
import os
import re
from datetime import datetime, timedelta, timezone

from .pricing import cost as model_cost

ISO_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}:\d{2})(\.\d+)?(Z|[+-]\d{2}:?\d{2})?$"
)


def parse_iso8601(text):
    # type: (str) -> "datetime | None"
    """Parse the ISO-8601 timestamps Claude Code writes, with or without fractions.

    ``datetime.fromisoformat`` on Python 3.8 rejects a trailing ``Z`` and any
    fraction that is not exactly 3 or 6 digits, so normalise first.
    """
    if not isinstance(text, str) or not text:
        return None
    m = ISO_RE.match(text.strip())
    if not m:
        return None
    day, clock, frac, offset = m.groups()
    micro = (frac or ".0")[1:][:6].ljust(6, "0")
    if offset in (None, "Z", "z"):
        tz = "+00:00"
    elif ":" in offset:
        tz = offset
    else:
        tz = offset[:3] + ":" + offset[3:]
    try:
        return datetime.fromisoformat("{}T{}.{}{}".format(day, clock, micro, tz))
    except ValueError:
        return None


class UsageEntry(object):
    """One assistant response's token usage."""

    __slots__ = ("key", "model", "date", "input", "output", "cache_create", "cache_read", "cost")

    def __init__(self, key, model, date, input_tokens, output_tokens, cache_create, cache_read, cost=None):
        self.key = key
        self.model = model
        self.date = date
        self.input = input_tokens
        self.output = output_tokens
        self.cache_create = cache_create
        self.cache_read = cache_read
        self.cost = cost if cost is not None else model_cost(model, input_tokens, output_tokens, cache_create, cache_read)

    @property
    def total(self):
        return self.input + self.output + self.cache_create + self.cache_read


class TokenTotals(object):
    """Running totals for a time window or a single model."""

    __slots__ = ("input", "output", "cache_create", "cache_read", "messages", "cost")

    def __init__(self):
        self.input = 0
        self.output = 0
        self.cache_create = 0
        self.cache_read = 0
        self.messages = 0
        self.cost = 0.0

    @property
    def total(self):
        return self.input + self.output + self.cache_create + self.cache_read

    def add(self, entry):
        # type: (UsageEntry) -> None
        self.input += entry.input
        self.output += entry.output
        self.cache_create += entry.cache_create
        self.cache_read += entry.cache_read
        self.messages += 1
        self.cost += entry.cost

    def to_dict(self):
        return {
            "input": self.input,
            "output": self.output,
            "cacheCreate": self.cache_create,
            "cacheRead": self.cache_read,
            "messages": self.messages,
            "total": self.total,
            "estimatedCostUSD": round(self.cost, 2),
        }


class ModelStats(object):
    __slots__ = ("model", "totals")

    def __init__(self, model):
        self.model = model
        self.totals = TokenTotals()

    @property
    def id(self):
        return self.model


class LocalStats(object):
    """Aggregated local usage for one account."""

    __slots__ = (
        "today", "last5h", "last7d", "last30d", "all_time",
        "per_model", "per_model_30d", "daily_peak_30", "scanned_at", "active_days_30", "weekly_peak_12",
    )

    def __init__(self):
        self.today = TokenTotals()
        self.last5h = TokenTotals()
        self.last7d = TokenTotals()
        self.last30d = TokenTotals()
        self.all_time = TokenTotals()
        self.per_model = []        # sorted by total tokens desc, all time
        self.per_model_30d = []    # sorted by total tokens desc, last 30 days
        self.active_days_30 = 0
        self.weekly_peak_12 = 0
        self.daily_peak_30 = 0     # busiest day (total tokens) in the last 30 days
        self.scanned_at = datetime.now(timezone.utc)

    @property
    def has_daily_baseline(self):
        return self.active_days_30 >= 3 and self.daily_peak_30 > 0

    @property
    def weekly_relative_percent(self):
        return min(100.0, self.last7d.total / self.weekly_peak_12 * 100) if self.weekly_peak_12 else 0.0

    @property
    def daily_relative_percent(self):
        # type: () -> float
        """Today's usage relative to the busiest day in the last 30 days (0-100)."""
        if self.daily_peak_30 <= 0:
            return 0.0
        return min(100.0, self.today.total / float(self.daily_peak_30) * 100.0)


class TranscriptScanner(object):
    """Scans Claude Code transcript JSONL files and aggregates token usage.

    Caches per-file results keyed by (mtime, size) so refreshes are cheap.
    """

    def __init__(self):
        self._cache = {}   # path -> (mtime, size, [UsageEntry])

    def scan(self, config_dir):
        # type: (str) -> LocalStats
        projects_dir = os.path.join(config_dir, "projects")
        all_entries = {}   # global dedup by key, latest wins
        live_paths = set()

        for root, dirnames, filenames in os.walk(projects_dir):
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            for name in filenames:
                if not name.endswith(".jsonl") or name.startswith("."):
                    continue
                path = os.path.join(root, name)
                try:
                    st = os.stat(path)
                except OSError:
                    continue
                live_paths.add(path)
                cached = self._cache.get(path)
                if cached is not None and cached[0] == st.st_mtime and cached[1] == st.st_size:
                    entries = cached[2]
                else:
                    entries = self._parse_file(path)
                    self._cache[path] = (st.st_mtime, st.st_size, entries)
                for e in entries:
                    existing = all_entries.get(e.key)
                    if existing is not None and existing.date > e.date:
                        continue
                    all_entries[e.key] = e

        # Drop cache entries for deleted files.
        for path in list(self._cache):
            if path not in live_paths:
                del self._cache[path]

        return self._aggregate(list(all_entries.values()))

    # -- internals ---------------------------------------------------------

    def _aggregate(self, entries):
        # type: (list) -> LocalStats
        stats = LocalStats()
        now = datetime.now(timezone.utc)
        local_tz = datetime.now().astimezone().tzinfo
        start_of_today = now.astimezone(local_tz).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        cutoff_7d = now - timedelta(days=7)
        cutoff_30d = now - timedelta(days=30)
        cutoff_5h = now - timedelta(hours=5)

        per_model = {}
        per_model_30d = {}
        daily_totals = {}
        history = {}

        for e in entries:
            if e.date > now:
                continue
            if e.date >= now - timedelta(days=90):
                day = e.date.astimezone().date()
                history[day] = history.get(day, 0) + e.total
            stats.all_time.add(e)
            m = per_model.get(e.model)
            if m is None:
                m = per_model[e.model] = ModelStats(e.model)
            m.totals.add(e)

            if e.date >= start_of_today:
                stats.today.add(e)
            if e.date >= cutoff_7d:
                stats.last7d.add(e)
            if e.date >= cutoff_30d:
                stats.last30d.add(e)
                m30 = per_model_30d.get(e.model)
                if m30 is None:
                    m30 = per_model_30d[e.model] = ModelStats(e.model)
                m30.totals.add(e)
                day = e.date.astimezone(local_tz).date()
                daily_totals[day] = daily_totals.get(day, 0) + e.total
            if e.date >= cutoff_5h:
                stats.last5h.add(e)

        stats.per_model = sorted(per_model.values(), key=lambda s: s.totals.total, reverse=True)
        stats.per_model_30d = sorted(per_model_30d.values(), key=lambda s: s.totals.total, reverse=True)
        stats.daily_peak_30 = max(daily_totals.values()) if daily_totals else 0
        stats.active_days_30 = len(daily_totals)
        stats.weekly_peak_12 = max((sum(history.get(day - timedelta(days=i), 0) for i in range(7)) for day in history), default=0)
        stats.scanned_at = now
        return stats

    def _parse_file(self, path):
        # type: (str) -> list
        by_key = {}
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                for line_no, line in enumerate(fh, start=1):
                    # Fast pre-filter: only assistant records carry usage.
                    if '"type":"assistant"' not in line and '"type": "assistant"' not in line:
                        continue
                    try:
                        obj = json.loads(line)
                    except ValueError:
                        continue
                    if not isinstance(obj, dict) or obj.get("type") != "assistant":
                        continue
                    message = obj.get("message")
                    if not isinstance(message, dict):
                        continue
                    model = message.get("model")
                    if not isinstance(model, str) or model == "<synthetic>":
                        continue
                    usage = message.get("usage")
                    if not isinstance(usage, dict):
                        continue

                    inp = _int(usage.get("input_tokens"))
                    out = _int(usage.get("output_tokens"))
                    cc = _int(usage.get("cache_creation_input_tokens"))
                    cr = _int(usage.get("cache_read_input_tokens"))
                    if inp + out + cc + cr == 0:
                        continue

                    date = parse_iso8601(obj.get("timestamp") or "")
                    if date is None:
                        continue

                    msg_id = message.get("id") or "{}:{}".format(os.path.basename(path), line_no)
                    req_id = obj.get("requestId") or ""
                    key = "{}:{}".format(msg_id, req_id)

                    # Streaming can write the same message on multiple lines; last one wins.
                    by_key[key] = UsageEntry(key, model, date, inp, out, cc, cr)
        except (OSError, UnicodeDecodeError):
            return []
        return list(by_key.values())


def _int(value):
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return max(0, value)
    if isinstance(value, float) and math.isfinite(value):
        return max(0, int(value))
    return 0


class Formatting(object):
    """Human-readable renderings shared by the panel and the CLI."""

    @staticmethod
    def tokens(n):
        # type: (int) -> str
        d = float(n)
        if n < 1000:
            return str(n)
        if n < 1_000_000:
            return "{:.1f}K".format(d / 1000)
        if n < 1_000_000_000:
            return "{:.1f}M".format(d / 1_000_000)
        return "{:.2f}B".format(d / 1_000_000_000)

    @staticmethod
    def usd(v):
        # type: (float) -> str
        return "${:.2f}".format(v) if v < 10 else "${:.0f}".format(v)

    @staticmethod
    def resets_in(date):
        # type: ("datetime | None") -> "str | None"
        if date is None:
            return None
        secs = (date - datetime.now(timezone.utc)).total_seconds()
        if secs <= 0:
            return None
        hours = int(secs) // 3600
        mins = (int(secs) % 3600) // 60
        if hours >= 24:
            return "resets in {}d {}h".format(hours // 24, hours % 24)
        if hours > 0:
            return "resets in {}h {}m".format(hours, mins)
        return "resets in {}m".format(mins)

    @staticmethod
    def clock(date):
        # type: ("datetime | None") -> str
        if date is None:
            return ""
        return date.astimezone().strftime("%H:%M")
