"""Tray icon, menu and window wiring (port of AppDelegate.swift).

GNOME has no click-to-open-a-view tray protocol: StatusNotifierItem can only
serialise a plain menu over D-Bus, so the icon opens a menu with a live usage
summary, and the full translucent panel is one click (or a middle click) away.
Desktops with a classic X11 tray get the direct click-to-open behaviour via
the Gtk.StatusIcon fallback.
"""

from __future__ import annotations

import importlib
import fcntl
import os
import signal
import sys

import gi

gi.require_version("Gtk", "3.0")

from gi.repository import GLib, Gtk   # noqa: E402

from . import status_icon             # noqa: E402
from .settings import PID_FILE, Settings, ensure_dir   # noqa: E402
from .state import AppState           # noqa: E402
from .settings_view import SettingsWindow   # noqa: E402
from .stats_view import StatsPanel    # noqa: E402
from .transcripts import Formatting   # noqa: E402

INDICATOR_ID = "trackai"


def _load_indicator_module():
    """Ayatana first (22.04+), then the older libappindicator (20.04)."""
    for name in ("AyatanaAppIndicator3", "AppIndicator3"):
        try:
            gi.require_version(name, "0.1")
            return importlib.import_module("gi.repository." + name)
        except (ImportError, ValueError):
            continue
    return None


class TrayApp(object):
    def __init__(self):
        self.settings = Settings.shared()
        self.state = AppState(self.settings)
        self.state.dispatch = self._dispatch
        self.state.add_listener(self._on_state_changed)
        self.settings.add_listener(self._on_settings_changed)

        self.icon_dir = status_icon.ensure_tray_icons()
        self.panel = StatsPanel(self.state, self.open_settings, self.quit)
        self.settings_window = None
        self._timer_id = None
        self._icon_state = None
        self._dynamic_items = []

        self.indicator_module = _load_indicator_module()
        self.indicator = None
        self.status_icon_fallback = None
        self.menu = self._build_menu()
        self._install_tray()

        self._install_signal_handlers()
        self._write_pid_file()

        self.state.start()
        self._reschedule_timer()

    # -- threading ---------------------------------------------------------

    def _dispatch(self, fn):
        GLib.idle_add(self._run_once, fn)

    @staticmethod
    def _run_once(fn):
        try:
            fn()
        except Exception as err:
            sys.stderr.write("trackai: UI update failed: {}\n".format(err))
        return False

    # -- tray --------------------------------------------------------------

    def _install_tray(self):
        module = self.indicator_module
        if module is not None:
            self.indicator = module.Indicator.new(
                INDICATOR_ID,
                status_icon.icon_name("gray"),
                module.IndicatorCategory.APPLICATION_STATUS,
            )
            if self.icon_dir:
                self.indicator.set_icon_theme_path(self.icon_dir)
            self.indicator.set_status(module.IndicatorStatus.ACTIVE)
            self.indicator.set_title("trackai")
            self.indicator.set_menu(self.menu)
            try:
                self.indicator.set_secondary_activate_target(self.open_item)
            except Exception:
                pass
            return

        # No AppIndicator available: fall back to the legacy X11 tray icon,
        # which supports opening the panel with a single left click.
        try:
            icon = Gtk.StatusIcon()
            path = None
            if self.icon_dir:
                path = os.path.join(self.icon_dir, status_icon.icon_name("gray") + ".png")
            if path and os.path.exists(path):
                icon.set_from_file(path)
            else:
                icon.set_from_icon_name("utilities-system-monitor-symbolic")
            icon.set_tooltip_text("trackai")
            icon.connect("activate", lambda *_: self.panel.toggle())
            icon.connect("popup-menu", self._on_status_icon_menu)
            self.status_icon_fallback = icon
        except Exception as err:
            sys.stderr.write(
                "trackai: no system tray available ({}).\n"
                "Install gir1.2-ayatanaappindicator3-0.1 and, on GNOME, enable the\n"
                "AppIndicator extension.\n".format(err)
            )

    def _on_status_icon_menu(self, icon, button, activate_time):
        self.menu.popup(None, None, Gtk.StatusIcon.position_menu, icon, button, activate_time)

    def _build_menu(self):
        menu = Gtk.Menu()

        self.open_item = Gtk.MenuItem(label="Open trackai panel")
        self.open_item.connect("activate", lambda *_: self.panel.show_panel())
        menu.append(self.open_item)

        menu.append(Gtk.SeparatorMenuItem())

        # Placeholder for the live summary lines, rebuilt on every refresh.
        self._summary_anchor = Gtk.SeparatorMenuItem()
        menu.append(self._summary_anchor)

        refresh_item = Gtk.MenuItem(label="Refresh now")
        refresh_item.connect("activate", lambda *_: self.state.refresh(force=True))
        menu.append(refresh_item)

        settings_item = Gtk.MenuItem(label="Settings…")
        settings_item.connect("activate", lambda *_: self.open_settings())
        menu.append(settings_item)

        menu.append(Gtk.SeparatorMenuItem())

        quit_item = Gtk.MenuItem(label="Quit trackai")
        quit_item.connect("activate", lambda *_: self.quit())
        menu.append(quit_item)

        menu.show_all()
        return menu

    def _rebuild_summary(self):
        for item in self._dynamic_items:
            self.menu.remove(item)
            item.destroy()
        self._dynamic_items = []

        lines = []
        if not self.state.accounts:
            lines.append("No providers found — run trackai setup")
        for data in self.state.accounts:
            lines.append(data.name)
            if data.api is not None:
                for limit in data.api.limits:
                    lines.append("{}  {:.0f}%".format(limit.display_name, limit.percent))
                lines.append("Limits observed " + data.api.fetched_at.astimezone().strftime("%b %d, %H:%M"))
            if data.api_error:
                lines.append(data.api_error)
            lines.append("Today  {} · {} est.".format(
                Formatting.tokens(data.local.today.total), Formatting.usd(data.local.today.cost)))

        position = 2   # after "Open panel" + separator
        for text in lines:
            item = Gtk.MenuItem(label=text)
            item.set_sensitive(False)
            self.menu.insert(item, position)
            item.show()
            self._dynamic_items.append(item)
            position += 1

    # -- icon --------------------------------------------------------------

    def _update_icon(self):
        data = self.state.menu_bar_account
        percent = self.state.icon_percent()
        state = self.settings.usage_color_name(percent) if percent is not None else "gray"
        label = ""
        if self.settings.show_percent_in_menu_bar and percent is not None:
            label = "{:.0f}%".format(percent)

        if self.indicator is not None:
            if state != self._icon_state:
                self.indicator.set_icon_full(status_icon.icon_name(state), "trackai usage")
                self._icon_state = state
            try:
                self.indicator.set_label(label, "100%")
            except Exception:
                pass
        elif self.status_icon_fallback is not None:
            if state != self._icon_state and self.icon_dir:
                path = os.path.join(self.icon_dir, status_icon.icon_name(state) + ".png")
                if os.path.exists(path):
                    self.status_icon_fallback.set_from_file(path)
                self._icon_state = state
            tooltip = "trackai"
            if percent is not None:
                tooltip = "trackai — {:.0f}%".format(percent)
            self.status_icon_fallback.set_tooltip_text(tooltip)

    # -- observers ---------------------------------------------------------

    def _on_state_changed(self):
        self._update_icon()
        self._rebuild_summary()
        if self.panel.get_visible():
            self.panel.rebuild()
        if self.settings_window is not None:
            self.settings_window.refresh_accounts()

    def _on_settings_changed(self):
        self._update_icon()
        self._reschedule_timer()
        self.state.refresh()
        if self.panel.get_visible():
            self.panel.queue_draw()
            self.panel.rebuild()

    # -- timer -------------------------------------------------------------

    def _reschedule_timer(self):
        if self._timer_id is not None:
            GLib.source_remove(self._timer_id)
            self._timer_id = None
        interval = int(max(30.0, float(self.settings.refresh_interval)))
        self._timer_id = GLib.timeout_add_seconds(interval, self._on_timer)

    def _on_timer(self):
        self.state.refresh()
        return True

    # -- windows -----------------------------------------------------------

    def open_settings(self):
        self.panel.hide_panel()
        if self.settings_window is None:
            self.settings_window = SettingsWindow(self.state, self._reschedule_timer)
        self.settings_window.present_window()

    # -- lifecycle ---------------------------------------------------------

    def _install_signal_handlers(self):
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, sig, self._on_signal)
            except Exception:
                signal.signal(sig, lambda *_: self.quit())

    def _on_signal(self):
        self.quit()
        return False

    def _write_pid_file(self):
        ensure_dir(os.path.dirname(PID_FILE))
        try:
            with open(PID_FILE, "w", encoding="utf-8") as fh:
                fh.write(str(os.getpid()))
        except OSError:
            pass

    def _remove_pid_file(self):
        try:
            with open(PID_FILE, "r", encoding="utf-8") as fh:
                if fh.read().strip() != str(os.getpid()):
                    return
        except OSError:
            return
        try:
            os.remove(PID_FILE)
        except OSError:
            pass

    def quit(self):
        self._remove_pid_file()
        Gtk.main_quit()

    def run(self):
        Gtk.main()


def run():
    # type: () -> int
    if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
        sys.stderr.write(
            "trackai: no graphical display found (DISPLAY/WAYLAND_DISPLAY unset).\n"
            "Run `trackai stats` for the command-line output instead.\n"
        )
        return 1
    ensure_dir(os.path.dirname(PID_FILE))
    lock = open(PID_FILE + ".lock", "a")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock.close()
        return 0
    ok, _ = Gtk.init_check(None)
    if not ok:
        sys.stderr.write("trackai: unable to connect to the graphical display. Use trackai stats.\n")
        lock.close()
        return 1
    app = TrayApp()
    try:
        app.run()
    finally:
        app._remove_pid_file()
        lock.close()
    return 0
