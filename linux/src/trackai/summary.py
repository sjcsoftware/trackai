"""The short summary the tray shows on hover.

One line per provider with only what decides whether you can keep working:
the session (5h) and weekly limits. The session's reset time is added once it
crosses the warning threshold, and stale Codex limits say how old they are.
No GTK here, so it is tested headlessly.
"""

from __future__ import annotations

from .credentials import STATUS_EXPIRED, STATUS_OK
from .transcripts import Formatting

STALE_MARK = "over 6 hours old"


def short_duration(date, now=None):
    # type: (object, object) -> "str | None"
    """'2h 05m', '3d 4h', '12m': Formatting.resets_in without the words."""
    text = Formatting.resets_in(date)
    return text[len("resets in "):] if text else None


def _percent(value):
    return "{:.0f}%".format(value)


def provider_line(data, settings):
    # type: (object, object) -> str
    name = data.name
    api = data.api
    session = api.limit("session") if api else None
    weekly = api.limit("weekly") if api else None
    if session is None and weekly is None:
        if data.credential_status == STATUS_EXPIRED:
            return name + " — login expired"
        if data.credential_status != STATUS_OK and not data.local.today.total:
            return name + " — not logged in"
        today = data.local.today
        if today.total:
            return "{} — today {} · {}".format(
                name, Formatting.tokens(today.total), Formatting.usd(today.cost))
        return name + " — no usage yet"

    parts = []
    if session is not None:
        text = "5h " + _percent(session.percent)
        left = short_duration(session.resets_at)
        if left and session.percent >= settings.warn_threshold:
            text += " (resets " + left + ")"
        parts.append(text)
    if weekly is not None:
        parts.append("week " + _percent(weekly.percent))
    line = name + " — " + " · ".join(parts)
    if data.api_error and STALE_MARK in data.api_error:
        line += " · as of " + Formatting.clock(api.fetched_at)
    return line


def tooltip(accounts, settings):
    # type: (list, object) -> tuple
    """(title, body) for the tray tooltip."""
    if not accounts:
        return "trackai", "No providers yet — log in to claude or codex"
    return "trackai", "\n".join(provider_line(d, settings) for d in accounts)


def label(percent):
    # type: ("float | None") -> str
    return _percent(percent) if percent is not None else ""
