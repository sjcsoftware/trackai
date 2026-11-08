"""A panel that drops from the tray icon and behaves like a menu.

On X11 it is an override-redirect window, so tiling window managers (i3,
bspwm, ...) never tile, float or move it, and it is placed beside the bar
under the click instead of on top of it. While it is open it holds a pointer
and keyboard grab, as GTK menus do: Escape or a click anywhere outside closes
it, and nothing else does. On Wayland, where clients cannot position or grab,
it is an undecorated top-level that closes on Escape or when it loses focus.
"""

from __future__ import annotations

import os
import time

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")

from gi.repository import Gdk, GLib, Gtk   # noqa: E402

from . import style, x11   # noqa: E402
from .placement import place   # noqa: E402

try:
    import cairo
except ImportError:
    cairo = None

GRAB_RETRY_MS = 30
GRAB_TIMEOUT_S = 1.5


def x11_popups_supported():
    # type: () -> bool
    if os.environ.get("WAYLAND_DISPLAY"):
        return False     # XWayland grabs are unreliable; use the toplevel path
    display = Gdk.Display.get_default()
    return display is not None and type(display).__name__ == "X11Display"


def _monitor_at(display, x, y):
    monitor = display.get_monitor_at_point(int(x), int(y))
    return monitor or display.get_primary_monitor() or display.get_monitor(0)


class PopupWindow(Gtk.Window):
    """Glass window that is shown at a tray click and dismissed like a menu."""

    radius = style.PANEL_RADIUS

    def __init__(self, settings):
        self.use_popup = x11_popups_supported()
        Gtk.Window.__init__(
            self, type=Gtk.WindowType.POPUP if self.use_popup else Gtk.WindowType.TOPLEVEL)
        style.install_css()
        self.settings = settings
        self._anchor = None         # (point, bar) in logical pixels
        self._grabbed = False
        self._grab_started = 0.0
        self._grab_source = 0
        self._shown_at = 0.0
        self._placing = False
        self._placed = None         # last (x, y, width, height) we moved to

        self.set_title("trackai")
        self.set_decorated(False)
        self.set_resizable(False)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.set_keep_above(True)
        # "utility" so compositors give it the treatment of a small tool window
        # (rounded corners, shadow, background blur where configured).
        self.set_type_hint(Gdk.WindowTypeHint.UTILITY)
        self.set_app_paintable(True)
        self.get_style_context().add_class("tc-root")
        self._apply_rgba_visual()

        self.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.KEY_PRESS_MASK)
        self.connect("draw", self._draw_background)
        self.connect("key-press-event", self._on_key_press)
        self.connect("button-press-event", self._on_button_press)
        self.connect("grab-broken-event", lambda *_: self.dismiss())
        self.connect("size-allocate", self._on_size_allocate)
        self.connect("delete-event", self._on_delete)
        if not self.use_popup:
            self.connect("focus-out-event", self._on_focus_out)

    # -- chrome ------------------------------------------------------------

    def _apply_rgba_visual(self):
        screen = self.get_screen()
        visual = screen.get_rgba_visual() if screen is not None else None
        self.composited = bool(visual is not None and screen.is_composited())
        if self.composited:
            self.set_visual(visual)

    def _draw_background(self, widget, cr):
        palette = style.Palette.current()
        width, height = widget.get_allocated_width(), widget.get_allocated_height()
        if cairo is not None:
            cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_rgba(0, 0, 0, 0)
        cr.paint()
        if cairo is not None:
            cr.set_operator(cairo.OPERATOR_OVER)
        alpha = self.settings.panel_alpha if self.composited else 1.0
        radius = self.radius if self.composited else 0
        style.rounded_rect(cr, 0.5, 0.5, width - 1, height - 1, radius)
        g = palette.glass
        cr.set_source_rgba(g[0], g[1], g[2], alpha)
        cr.fill_preserve()
        ink, edge_alpha = palette.edge
        cr.set_source_rgba(ink[0], ink[1], ink[2], edge_alpha)
        cr.set_line_width(1.0)
        cr.stroke()
        return False

    # -- showing -----------------------------------------------------------

    def popup_at(self, root_x=None, root_y=None, anchor_rect=None):
        """Open at a tray click in root (device) pixels, or at ``anchor_rect``
        (x, y, w, h, also device pixels) when the host gave an icon area."""
        display = Gdk.Display.get_default()
        if root_x is None or (root_x <= 0 and root_y <= 0):
            # Hosts that pass (0, 0) never said where; the pointer is there.
            if anchor_rect is not None:
                root_x = anchor_rect[0] + anchor_rect[2] // 2
                root_y = anchor_rect[1] + anchor_rect[3] // 2
            else:
                _screen, root_x, root_y = display.get_default_seat().get_pointer().get_position()[0:3]
                scale = _monitor_at(display, root_x, root_y).get_scale_factor()
                root_x, root_y = root_x * scale, root_y * scale
        # X11 scales every monitor alike (GDK_SCALE); hosts report device pixels.
        scale = max(1, _monitor_at(display, 0, 0).get_scale_factor())
        bar = x11.toplevel_rect_at(root_x, root_y, self._own_xids()) if self.use_popup else None
        point = (root_x // scale, root_y // scale)
        if bar is not None:
            bar = tuple(v // scale for v in bar)
        self._anchor = (point, bar)
        self._placed = None
        self.show_all()
        self._place()
        self._shown_at = time.monotonic()
        if self.use_popup:
            self._start_grab()
        else:
            self.present_with_time(Gtk.get_current_event_time())

    def _own_xids(self):
        window = self.get_window()
        try:
            return {window.get_xid()} if window is not None else set()
        except AttributeError:
            return set()

    def _place(self):
        if self._anchor is None or self._placing:
            return
        display = Gdk.Display.get_default()
        point, bar = self._anchor
        monitor = _monitor_at(display, point[0], point[1])
        geo = monitor.get_geometry()
        width, height = self.get_size()
        x, y = place((width, height), point, bar, (geo.x, geo.y, geo.width, geo.height))
        if self._placed == (x, y, width, height):
            return
        self._placed = (x, y, width, height)
        self._placing = True
        try:
            self.move(x, y)
        finally:
            self._placing = False

    def _on_size_allocate(self, *_args):
        # Content changes (a refresh, switching pages) change the height; a
        # panel above a bottom bar must grow upward, so re-place every time.
        if self.get_visible():
            GLib.idle_add(lambda: self._place() and False)

    # -- grab --------------------------------------------------------------

    def _start_grab(self):
        self._grab_started = time.monotonic()
        if self._grab_source:
            GLib.source_remove(self._grab_source)
        self._grab_source = 0
        if self._try_grab():
            self._grab_source = GLib.timeout_add(GRAB_RETRY_MS, self._try_grab)

    def _try_grab(self):
        """True to retry: the tray host may still hold its own grab from the
        click that opened us until the button is released."""
        window = self.get_window()
        if window is None or not self.get_visible():
            self._grab_source = 0
            return False
        seat = Gdk.Display.get_default().get_default_seat()
        status = seat.grab(window, Gdk.SeatCapabilities.ALL, True, None, None, None, None)
        if status == Gdk.GrabStatus.SUCCESS:
            self._grabbed = True
            self._grab_source = 0
            return False
        if time.monotonic() - self._grab_started > GRAB_TIMEOUT_S:
            self._grab_source = 0
            return False
        return True

    def _release_grab(self):
        if self._grab_source:
            GLib.source_remove(self._grab_source)
            self._grab_source = 0
        if self._grabbed:
            Gdk.Display.get_default().get_default_seat().ungrab()
            self._grabbed = False

    # -- dismissing --------------------------------------------------------

    def dismiss(self):
        self._release_grab()
        self.hide()
        return False

    def toggle_at(self, root_x=None, root_y=None, anchor_rect=None):
        if self.get_visible():
            self.dismiss()
        else:
            self.popup_at(root_x, root_y, anchor_rect)

    def _on_button_press(self, _widget, event):
        # Under the grab, clicks outside every window of ours are reported here.
        window = self.get_window()
        if window is None:
            return False
        ox, oy = window.get_origin()[1:3]
        width, height = self.get_size()
        inside = ox <= event.x_root < ox + width and oy <= event.y_root < oy + height
        if not inside:
            self.dismiss()
            return True
        return False

    def _on_key_press(self, _widget, event):
        if event.keyval == Gdk.KEY_Escape:
            self.dismiss()
            return True
        return False

    def _on_focus_out(self, *_args):
        # Ignore the focus churn that happens while the window is mapping.
        if time.monotonic() - self._shown_at > 0.6:
            self.dismiss()
        return False

    def _on_delete(self, *_args):
        self.dismiss()
        return True      # never destroy; the tray icon owns the lifecycle
