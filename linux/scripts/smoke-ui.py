#!/usr/bin/env python3
"""Render all GTK views with synthetic data; use xvfb-run on CI."""
import os
from pathlib import Path
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone

sandbox = tempfile.TemporaryDirectory(prefix="trackai-ui-")
for key, part in (("XDG_CONFIG_HOME", "config"), ("XDG_CACHE_HOME", "cache")):
    os.environ[key] = str(Path(sandbox.name) / part)
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import gi
gi.require_version("Gtk", "3.0")
gi.require_foreign("cairo")
from gi.repository import Gtk, Gdk
from trackai.providers import ProviderSnapshot
from trackai.settings import Settings
from trackai.state import AppState
from trackai.stats_view import StatsPanel
from trackai.settings_view import SettingsWindow
from trackai.transcripts import TranscriptScanner, UsageEntry
from trackai.usage_api import ApiUsage, LimitInfo

out = Path(sys.argv[1] if len(sys.argv) > 1 else sandbox.name)
out.mkdir(parents=True, exist_ok=True)
settings = Settings()
settings.opaque_background = True
state = AppState(settings)
state.refresh = lambda *a, **kw: None
now = datetime.now(timezone.utc)
for kind, name, model, percent in (("claude", "Claude Code", "claude-sonnet-5", 32), ("codex", "Codex", "gpt-5.5", 68)):
    data = ProviderSnapshot(kind, name, "/fixture/" + kind)
    data.account.email = "developer@example.invalid"
    data.subscription_type = "plus" if kind == "codex" else "pro"
    data.credential_status = "ok"
    data.local = TranscriptScanner()._aggregate([
        UsageEntry(str(i), model, now - timedelta(days=i, minutes=10), 40000, 20000, 0, 150000)
        for i in range(4)])
    data.api = ApiUsage([LimitInfo("session", "session", percent, now + timedelta(hours=2)),
                         LimitInfo("weekly", "weekly", percent / 2, now + timedelta(days=3))], None,
                        now - timedelta(hours=8 if kind == "codex" else 0))
    if kind == "codex":
        data.api_error = "Limits as of the last Codex run (over 6 hours old)"
    state.accounts.append(data)
state.last_refresh = now
panel = StatsPanel(state, lambda: None, lambda: None)


def render(window, name):
    window._shown_at = time.time()
    window.show_all()
    window.present()
    deadline = time.monotonic() + 0.3
    while time.monotonic() < deadline:
        while Gtk.events_pending():
            Gtk.main_iteration_do(False)
        time.sleep(0.01)
    width, height = window.get_size()
    assert width > 100 and height > 100
    pixbuf = Gdk.pixbuf_get_from_window(window.get_window(), 0, 0, width, height)
    assert pixbuf is not None
    pixbuf.savev(str(out / (name + ".png")), "png", [], [])
    window.hide()


render(panel, "linux-overview")
panel.detailed = True
panel.rebuild()
render(panel, "linux-detailed")
window = SettingsWindow(state, lambda: None)
render(window, "linux-settings")
# Exercise actual controls, order/enabling, and empty/single provider rebuilds.
window._move_provider(None, "codex", -1)
assert settings.provider_order[0] == "codex"
window.metric_combo.set_active_id("weekly")
assert settings.color_metric == "weekly"
window.warn_scale.set_value(90)
assert settings.warn_threshold <= settings.crit_threshold
for data in (state.accounts[:1], []):
    state.accounts = data
    panel.rebuild()
    render(panel, "linux-empty" if not data else "linux-single")
window.destroy()
panel.destroy()
print("GTK overview, detailed, settings, ordering, thresholds, and empty/single-provider smoke checks passed")
