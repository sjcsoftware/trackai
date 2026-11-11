"""Tray icon, panel and settings wiring (port of AppDelegate.swift).

The icon is a StatusNotifierItem we serve ourselves (``sni``), which every
modern tray speaks: KDE, the GNOME AppIndicator extension, waybar, eww,
polybar's and xfce4-panel's SNI plugins. A click opens the panel at the icon;
there is deliberately no hover tooltip. Without a StatusNotifierWatcher
(i3bar, stalonetray, older panels) the classic XEmbed tray icon takes over.
If a watcher appears later (a bar that starts after us), we switch to it.
"""

from __future__ import annotations

import fcntl
import os
import signal
import sys
import warnings

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")

from gi.repository import Gdk, GLib, Gtk   # noqa: E402

from . import sni, status_icon   # noqa: E402
from .settings import PID_FILE, Settings, ensure_dir   # noqa: E402
from .state import AppState           # noqa: E402
from .settings_view import SettingsWindow   # noqa: E402
from .stats_view import StatsPanel   # noqa: E402

ITEM_ID = "trackai"
XEMBED_SIZE = 22


class TrayApp(object):
    def __init__(self):
        self.settings = Settings.shared()
        self.state = AppState(self.settings)
        self.state.dispatch = self._dispatch
        self.state.add_listener(self._on_state_changed)
        self.settings.add_listener(self._on_settings_changed)

        self.panel = StatsPanel(self.state, self.open_settings, self.quit)
        self.settings_window = None
        self._timer_id = None
        self._xembed = None
        self._xembed_size = XEMBED_SIZE
        self._appearance = None

        self.item = sni.StatusNotifierItem(ITEM_ID, self._on_item_activate,
                                           self._on_host_changed)
        if not self.item.start():
            self._show_xembed(True)
        else:
            # Give an existing watcher a moment to accept us before falling back.
            GLib.timeout_add(1500, self._fallback_if_unregistered)

        self._update_tray()
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

    # -- tray hosts --------------------------------------------------------

    def _on_item_activate(self, x, y):
        self.panel.toggle_at(x, y)

    def _on_host_changed(self, available):
        self._show_xembed(not available)

    def _fallback_if_unregistered(self):
        if not self.item.registered:
            self._show_xembed(True)
        return False

    def _show_xembed(self, visible):
        if not visible:
            if self._xembed is not None:
                self._xembed.set_visible(False)
            return
        if self._xembed is None:
            display = Gdk.Display.get_default()
            if display is None or type(display).__name__ != "X11Display":
                return      # the XEmbed tray only exists on X11
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")   # deprecated in GTK, still the only XEmbed API
                    icon = Gtk.StatusIcon()
            except Exception as err:
                sys.stderr.write("trackai: no system tray available ({}).\n".format(err))
                return
            icon.set_title("trackai")
            icon.set_has_tooltip(False)
            icon.connect("activate", self._on_xembed_click)
            icon.connect("popup-menu", lambda icon, *_: self._on_xembed_click(icon))
            icon.connect("size-changed", self._on_xembed_size)
            self._xembed = icon
            self._appearance = None
            self._update_tray()
        self._xembed.set_visible(True)

    def _on_xembed_click(self, icon):
        ok, _screen, area, _orientation = icon.get_geometry()
        rect = (area.x, area.y, area.width, area.height) if ok else None
        self.panel.toggle_at(None, None, rect)

    def _on_xembed_size(self, _icon, size):
        self._xembed_size = max(16, int(size))
        self._appearance = None
        self._update_tray()
        return True

    # -- icon --------------------------------------------------------------

    def _update_tray(self):
        percent = self.state.icon_percent()
        state = self.settings.usage_color_name(percent) if percent is not None else "gray"
        kind = self.state.icon_kind()
        # Drawn into the icon rather than sent as an SNI label: most hosts
        # (eww, KDE, waybar, XEmbed) never show labels.
        show = self.settings.show_percent_in_menu_bar and percent is not None
        beside = self.settings.percent_placement == "beside"
        self.item.set_icon(status_icon.pixmaps(
            state, kind, percent,
            status_icon.percent_text(percent, sign=beside) if show else None, beside))
        # The XEmbed tray only holds square icons, so it always puts it under.
        text = status_icon.percent_text(percent) if show else None

        if self._xembed is not None:
            level = None if kind else int(round((percent or 0) / 5.0)) * 5
            appearance = (state, kind, level, text, self._xembed_size)
            if appearance != self._appearance:
                pixbuf = status_icon.pixbuf(self._xembed_size, state, kind, level, text)
                if pixbuf is not None:
                    self._xembed.set_from_pixbuf(pixbuf)
                else:
                    self._xembed.set_from_icon_name("utilities-system-monitor-symbolic")
                self._appearance = appearance

    # -- observers ---------------------------------------------------------

    def _on_state_changed(self):
        self._update_tray()
        if self.panel.get_visible():
            self.panel.rebuild()
        if self.settings_window is not None:
            self.settings_window.refresh_accounts()

    def _on_settings_changed(self):
        self._update_tray()
        self._reschedule_timer()
        self.state.refresh()
        if self.panel.get_visible():
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
        self.panel.dismiss()
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
        self.panel.dismiss()
        self.item.stop()
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
