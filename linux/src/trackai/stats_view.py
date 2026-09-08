"""The translucent stats panel (port of StatsView.swift).

macOS gets NSVisualEffectView blur for free; on Linux the closest honest
equivalent is an RGBA window whose background alpha follows the transparency
setting, with rounded corners drawn in cairo and frosted section blocks.
"""

from __future__ import annotations

import math
import time
from datetime import datetime, timezone

import gi

gi.require_version("Gtk", "3.0")

from gi.repository import Gdk, Gtk, Pango   # noqa: E402

from . import status_icon                    # noqa: E402
from .credentials import STATUS_EXPIRED, STATUS_MISSING, STATUS_OK   # noqa: E402
from .pricing import pretty_model_name       # noqa: E402
from .settings import COLOR_GRAY, Settings   # noqa: E402
from .transcripts import Formatting          # noqa: E402

try:
    import cairo
except ImportError:
    cairo = None

PANEL_WIDTH = 360
PANEL_MAX_SCROLL_HEIGHT = 460
CORNER_RADIUS = 16

CSS = b"""
#tc-panel { background-color: transparent; }
.tc-title { font-size: 13px; font-weight: bold; }
.tc-section-title { font-size: 9px; font-weight: bold; opacity: 0.72; }
.tc-name { font-size: 12px; font-weight: 500; }
.tc-value { font-size: 11px; font-weight: 600; font-family: monospace; opacity: 0.78; }
.tc-line { font-size: 11px; opacity: 0.78; }
.tc-line-value { font-size: 11px; font-family: monospace; opacity: 0.78; }
.tc-sub { font-size: 10px; opacity: 0.55; }
.tc-note { font-size: 11px; opacity: 0.78; }
.tc-warn { font-size: 11px; color: #ff9500; }
.tc-block {
    border-radius: 12px;
    border: 1px solid rgba(128, 128, 128, 0.28);
    padding: 12px;
}
.tc-block-dark { background-color: rgba(255, 255, 255, 0.06); }
.tc-block-light { background-color: rgba(0, 0, 0, 0.04); }
.tc-tab {
    font-size: 10px;
    border-radius: 11px;
    padding: 2px 10px;
    min-height: 0;
}
.tc-iconbutton { padding: 2px; min-width: 22px; min-height: 22px; }
"""

_css_loaded = False


def install_css():
    global _css_loaded
    if _css_loaded:
        return
    screen = Gdk.Screen.get_default()
    if screen is None:
        return
    provider = Gtk.CssProvider()
    try:
        provider.load_from_data(CSS)
    except Exception:
        return
    Gtk.StyleContext.add_provider_for_screen(
        screen, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
    )
    _css_loaded = True


def prefers_dark():
    # type: () -> bool
    gtk_settings = Gtk.Settings.get_default()
    if gtk_settings is None:
        return True
    try:
        if gtk_settings.get_property("gtk-application-prefer-dark-theme"):
            return True
        theme = gtk_settings.get_property("gtk-theme-name") or ""
    except Exception:
        return True
    return "dark" in theme.lower()


def _label(text, css_class, xalign=0.0, ellipsize=False):
    label = Gtk.Label(label=text)
    label.set_xalign(xalign)
    label.get_style_context().add_class(css_class)
    if ellipsize:
        label.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        label.set_max_width_chars(28)
    else:
        label.set_line_wrap(True)
        label.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
    return label


class BarRow(Gtk.Box):
    """A labelled usage bar: name, value, coloured capsule, optional subtitle."""

    def __init__(self, name, percent, value_text, subtitle=None, settings=None):
        Gtk.Box.__init__(self, orientation=Gtk.Orientation.VERTICAL, spacing=3)
        self.settings = settings or Settings.shared()
        self.percent = max(0.0, float(percent))

        head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        name_label = _label(name, "tc-name", ellipsize=True)
        name_label.set_hexpand(True)
        head.pack_start(name_label, True, True, 0)
        head.pack_end(_label(value_text, "tc-value", xalign=1.0, ellipsize=True), False, False, 0)
        self.pack_start(head, False, False, 0)

        bar = Gtk.DrawingArea()
        bar.set_size_request(-1, 6)
        bar.connect("draw", self._draw_bar)
        self.pack_start(bar, False, False, 0)

        if subtitle:
            self.pack_start(_label(subtitle, "tc-sub"), False, False, 0)

    def _draw_bar(self, widget, cr):
        width = widget.get_allocated_width()
        height = widget.get_allocated_height()
        radius = height / 2.0
        fraction = min(1.0, self.percent / 100.0)
        fill_width = width * fraction

        dark = prefers_dark()
        track = (1.0, 1.0, 1.0, 0.14) if dark else (0.0, 0.0, 0.0, 0.09)
        _rounded_rect(cr, 0, 0, width, height, radius)
        cr.set_source_rgba(*track)
        cr.fill()

        rgb = self.settings.usage_color(self.percent)
        _rounded_rect(cr, 0, 0, fill_width, height, radius)
        cr.set_source_rgb(rgb[0], rgb[1], rgb[2])
        cr.fill()
        return False


def _rounded_rect(cr, x, y, width, height, radius):
    radius = max(0.0, min(radius, width / 2.0, height / 2.0))
    cr.new_sub_path()
    cr.arc(x + width - radius, y + radius, radius, -math.pi / 2, 0)
    cr.arc(x + width - radius, y + height - radius, radius, 0, math.pi / 2)
    cr.arc(x + radius, y + height - radius, radius, math.pi / 2, math.pi)
    cr.arc(x + radius, y + radius, radius, math.pi, 1.5 * math.pi)
    cr.close_path()


class SectionBlock(Gtk.Box):
    """A softly rounded frosted box grouping one section of stats."""

    def __init__(self, title):
        Gtk.Box.__init__(self, orientation=Gtk.Orientation.VERTICAL, spacing=9)
        ctx = self.get_style_context()
        ctx.add_class("tc-block")
        ctx.add_class("tc-block-dark" if prefers_dark() else "tc-block-light")
        self.pack_start(_label(title.upper(), "tc-section-title"), False, False, 0)

    def add_row(self, widget):
        self.pack_start(widget, False, False, 0)


class StatsPanel(Gtk.Window):
    """The panel that opens from the tray icon."""

    def __init__(self, state, on_open_settings, on_quit):
        Gtk.Window.__init__(self, type=Gtk.WindowType.TOPLEVEL)
        install_css()
        self.state = state
        self.settings = state.settings
        self.on_open_settings = on_open_settings
        self.on_quit = on_quit
        self._shown_at = 0.0
        self.detailed = False

        self.set_name("tc-panel")
        self.set_title("trackai")
        self.set_decorated(False)
        self.set_resizable(False)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.set_keep_above(True)
        self.set_type_hint(Gdk.WindowTypeHint.UTILITY)
        self.set_app_paintable(True)
        self.set_default_size(PANEL_WIDTH, -1)
        self.set_border_width(0)

        self._apply_rgba_visual()
        self.connect("draw", self._draw_background)
        self.connect("focus-out-event", self._on_focus_out)
        self.connect("key-press-event", self._on_key_press)
        self.connect("delete-event", self._on_delete)

        self.root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.root.set_border_width(14)
        self.add(self.root)
        self.rebuild()

    # -- window chrome -----------------------------------------------------

    def _apply_rgba_visual(self):
        screen = self.get_screen()
        if screen is None:
            return
        visual = screen.get_rgba_visual()
        if visual is not None and screen.is_composited():
            self.set_visual(visual)

    def _draw_background(self, widget, cr):
        if cairo is not None:
            cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_rgba(0, 0, 0, 0)
        cr.paint()
        if cairo is not None:
            cr.set_operator(cairo.OPERATOR_OVER)

        width = widget.get_allocated_width()
        height = widget.get_allocated_height()
        alpha = self.settings.panel_alpha
        base = (0.13, 0.13, 0.14) if prefers_dark() else (0.97, 0.97, 0.98)
        _rounded_rect(cr, 0, 0, width, height, CORNER_RADIUS)
        cr.set_source_rgba(base[0], base[1], base[2], alpha)
        cr.fill_preserve()
        edge = (1.0, 1.0, 1.0, 0.14) if prefers_dark() else (0.0, 0.0, 0.0, 0.12)
        cr.set_line_width(1.0)
        cr.set_source_rgba(*edge)
        cr.stroke()
        return False

    def _on_focus_out(self, *_args):
        # Ignore the focus churn that happens while the window is mapping.
        if time.time() - self._shown_at > 0.6:
            self.hide_panel()
        return False

    def _on_key_press(self, _widget, event):
        if event.keyval == Gdk.KEY_Escape:
            self.hide_panel()
            return True
        return False

    def _on_delete(self, *_args):
        self.hide_panel()
        return True    # never destroy; the tray icon owns the lifecycle

    # -- show / hide -------------------------------------------------------

    def toggle(self):
        if self.get_visible():
            self.hide_panel()
        else:
            self.show_panel()

    def show_panel(self):
        self.rebuild()
        self.show_all()
        self._position()
        self._shown_at = time.time()
        self.present_with_time(Gtk.get_current_event_time())
        self.state.refresh()

    def hide_panel(self):
        self.hide()

    def _position(self):
        display = Gdk.Display.get_default()
        if display is None:
            return
        monitor = None
        try:
            monitor = display.get_primary_monitor()
        except Exception:
            monitor = None
        if monitor is None:
            try:
                monitor = display.get_monitor(0)
            except Exception:
                monitor = None
        if monitor is None:
            return
        area = monitor.get_workarea()
        width, height = self.get_size()
        x = area.x + area.width - width - 12
        y = area.y + 12
        # Keep the panel inside the work area if it is taller than the screen.
        if y + height > area.y + area.height:
            y = max(area.y, area.y + area.height - height - 12)
        self.move(x, y)

    # -- content -----------------------------------------------------------

    def rebuild(self):
        for child in self.root.get_children():
            self.root.remove(child)
            child.destroy()

        self.root.pack_start(self._header(), False, False, 0)

        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        if not self.state.accounts:
            body.pack_start(_label("No providers found. Run `claude` and/or `codex`, log in, then refresh.", "tc-note"), False, False, 0)
        for data in self.state.accounts:
            block = SectionBlock(data.name)
            if data.account.email:
                block.add_row(_label(data.account.email, "tc-sub"))
            if self.detailed:
                block.add_row(self._plan_section(data))
                block.add_row(self._local_section(data))
                if data.local.per_model_30d:
                    block.add_row(self._model_section(data.local))
                block.add_row(self._footer(data))
            else:
                for metric, title in (("session", "Session"), ("daily", "Daily"), ("weekly", "Weekly")):
                    percent = data.metric_percent(metric)
                    limit = data.api.limit(metric) if data.api else None
                    if limit:
                        title = limit.display_name
                    if metric == "daily":
                        value = "{} · {} est.".format(Formatting.tokens(data.local.today.total), Formatting.usd(data.local.today.cost))
                        subtitle = "vs. busiest day in 30 days" if data.local.has_daily_baseline else "Collecting daily history"
                    else:
                        value = "{:.0f}%".format(percent) if percent is not None else "—"
                        subtitle = Formatting.resets_in(limit.resets_at) if limit else ("Local usage vs. busiest week in 90 days" if metric == "weekly" else "No plan-limit data")
                    block.add_row(BarRow(title, percent or 0, value, subtitle, self.settings))
                if data.api:
                    block.add_row(_label("Limits observed " + self._observed_at(data.api.fetched_at), "tc-sub"))
                if data.api_error:
                    block.add_row(_label(data.api_error, "tc-warn"))
                if data.credential_status != STATUS_OK:
                    block.add_row(_label(data.credential_status + " — run the provider CLI to log in", "tc-warn"))
            body.pack_start(block, False, False, 0)
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_max_content_height(PANEL_MAX_SCROLL_HEIGHT)
        scroller.set_propagate_natural_height(True)
        scroller.add(body)
        self.root.pack_start(scroller, True, True, 0)
        pages = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        for title, detailed in (("Overview", False), ("Detailed", True)):
            button = Gtk.ToggleButton(label=title)
            button.set_active(self.detailed == detailed)
            button.connect("clicked", self._change_page, detailed)
            pages.pack_start(button, True, True, 0)
        self.root.pack_start(pages, False, False, 0)

        self.root.show_all()

    def _header(self):
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)

        icon = Gtk.DrawingArea()
        icon.set_size_request(16, 16)
        icon.connect("draw", self._draw_header_icon)
        icon.set_valign(Gtk.Align.CENTER)
        box.pack_start(icon, False, False, 0)
        box.pack_start(_label("trackai", "tc-title"), False, False, 0)

        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        box.pack_start(spacer, True, True, 0)

        box.pack_end(self._icon_button("system-shutdown-symbolic", "Quit trackai",
                                       lambda *_: self.on_quit()), False, False, 0)
        box.pack_end(self._icon_button("emblem-system-symbolic", "Settings",
                                       lambda *_: self.on_open_settings()), False, False, 0)
        refresh = self._icon_button("view-refresh-symbolic", "Refresh now",
                                    lambda *_: self.state.refresh(force=True))
        refresh.set_sensitive(not self.state.is_refreshing)
        box.pack_end(refresh, False, False, 0)
        return box

    def _icon_button(self, icon_name, tooltip, callback):
        button = Gtk.Button.new_from_icon_name(icon_name, Gtk.IconSize.MENU)
        button.set_relief(Gtk.ReliefStyle.NONE)
        button.set_tooltip_text(tooltip)
        button.get_style_context().add_class("tc-iconbutton")
        button.connect("clicked", callback)
        return button

    def _draw_header_icon(self, widget, cr):
        data = self.state.menu_bar_account
        percent = self.state.icon_percent()
        rgb = self.settings.usage_color(percent) if percent is not None else COLOR_GRAY
        status_icon.draw_bolt(cr, 16, rgb)
        return False

    def _change_page(self, _button, detailed):
        if self.detailed != detailed:
            self.detailed = detailed
            self.rebuild()

    @staticmethod
    def _observed_at(date):
        return date.astimezone().strftime("%b %d, %H:%M")

    def _plan_section(self, data):
        block = SectionBlock("Plan limits")
        api = data.api
        if api is not None:
            for limit in api.limits:
                block.add_row(BarRow(
                    limit.display_name,
                    limit.percent,
                    "{:.0f}%".format(limit.percent),
                    Formatting.resets_in(limit.resets_at),
                    self.settings,
                ))
            if api.extra_credits_used is not None:
                block.add_row(_label(
                    "Extra usage credits used: " + Formatting.usd(api.extra_credits_used),
                    "tc-sub",
                ))
            if (datetime.now(timezone.utc) - api.fetched_at).total_seconds() > 600:
                block.add_row(_label("as of " + Formatting.clock(api.fetched_at), "tc-sub"))
        else:
            block.add_row(_label(data.api_error or "No plan limits available yet. Run the provider CLI, then refresh.", "tc-note"))
        if data.api:
            block.add_row(_label("Limits observed " + self._observed_at(data.api.fetched_at), "tc-sub"))
            if data.api_error:
                block.add_row(_label(data.api_error, "tc-warn"))
        if data.credential_status != STATUS_OK:
            block.add_row(_label(data.credential_status + " — run the provider CLI to log in", "tc-warn"))
        return block

    def _local_section(self, data):
        block = SectionBlock("Token usage (local, estimated cost)")
        local = data.local
        if local is None:
            block.add_row(_label("No transcripts found yet.", "tc-note"))
            return block

        block.add_row(BarRow(
            "Today",
            local.daily_relative_percent if local.has_daily_baseline else 0,
            "{} · {}".format(Formatting.tokens(local.today.total), Formatting.usd(local.today.cost)),
            ("vs. busiest day in last 30 days" if local.has_daily_baseline else "Collecting daily history"),
            self.settings,
        ))
        for name, totals in (
            ("Last 5 hours", local.last5h),
            ("Last 7 days", local.last7d),
            ("Last 30 days", local.last30d),
            ("All time", local.all_time),
        ):
            block.add_row(self._stat_line(name, totals))
        totals = local.last30d
        block.add_row(_label("30d: in {} · out {} · cache write {} · cache read {}".format(
            Formatting.tokens(totals.input), Formatting.tokens(totals.output),
            Formatting.tokens(totals.cache_create), Formatting.tokens(totals.cache_read)), "tc-sub"))
        return block

    def _stat_line(self, name, totals):
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        row.pack_start(_label(name, "tc-line"), False, False, 0)
        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        row.pack_start(spacer, True, True, 0)
        value = "{} · {}".format(Formatting.tokens(totals.total), Formatting.usd(totals.cost))
        row.pack_end(_label(value, "tc-line-value", xalign=1.0), False, False, 0)
        return row

    def _model_section(self, local):
        block = SectionBlock("By model (last 30 days, estimated cost)")
        top = local.last30d.total or 1
        for stats in local.per_model_30d:
            totals = stats.totals
            block.add_row(BarRow(
                pretty_model_name(stats.model),
                totals.total / float(max(1, top)) * 100.0,
                "{} · {}".format(Formatting.tokens(totals.total), Formatting.usd(totals.cost)),
                "in {} · out {} · cache {}".format(
                    Formatting.tokens(totals.input),
                    Formatting.tokens(totals.output),
                    Formatting.tokens(totals.cache_create + totals.cache_read),
                ),
                self.settings,
            ))
        return block

    def _footer(self, data):
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        if data.subscription_type:
            text = data.subscription_type.capitalize()
            if data.rate_limit_tier:
                text += " · " + data.rate_limit_tier
            row.pack_start(_label(text, "tc-sub"), False, False, 0)
        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        row.pack_start(spacer, True, True, 0)
        if self.state.last_refresh is not None:
            row.pack_end(
                _label("updated " + Formatting.clock(self.state.last_refresh), "tc-sub", xalign=1.0),
                False, False, 0,
            )
        return row
