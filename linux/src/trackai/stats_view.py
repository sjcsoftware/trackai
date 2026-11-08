"""The stats panel (port of PanelView/ProviderBoxes.swift).

The panel has the macOS layout: a header with the aggregate icon, one card
per provider, and a footer with the Overview/Detailed switch.
"""

from __future__ import annotations

from datetime import datetime, timezone

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")

from gi.repository import Gtk, Pango   # noqa: E402

from . import provider_mark, status_icon, style   # noqa: E402
from .credentials import STATUS_EXPIRED, STATUS_OK   # noqa: E402
from .popup import PopupWindow                      # noqa: E402
from .pricing import pretty_model_name              # noqa: E402
from .providers import commands_hint                # noqa: E402
from .settings import COLOR_GRAY, Settings          # noqa: E402
from .transcripts import Formatting                 # noqa: E402

try:
    import cairo
except ImportError:
    cairo = None

PANEL_WIDTH = 340
OVERVIEW_MAX_HEIGHT = 600   # three provider cards without scrolling
DETAILED_MAX_HEIGHT = 600

# Kept for older imports (settings_view, smoke tests).
install_css = style.install_css
prefers_dark = style.prefers_dark


def _label(text, css_class, xalign=0.0, wrap=False, ellipsize=False):
    label = Gtk.Label(label=text)
    label.set_xalign(xalign)
    label.get_style_context().add_class(css_class)
    if ellipsize:
        label.set_ellipsize(Pango.EllipsizeMode.END)
    elif wrap:
        label.set_line_wrap(True)
        label.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
        label.set_max_width_chars(40)
    return label


def _hbox(spacing=6):
    return Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=spacing)


def _vbox(spacing=0):
    return Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=spacing)


def _spacer():
    box = Gtk.Box()
    box.set_hexpand(True)
    return box


def _ago(date):
    if date is None:
        return ""
    secs = (datetime.now(timezone.utc) - date).total_seconds()
    if secs < 60:
        return "updated just now"
    if secs < 3600:
        return "updated {}m ago".format(int(secs // 60))
    return "updated " + Formatting.clock(date)


class Bar(Gtk.DrawingArea):
    """A capsule track with a fill; usage colour unless ``tint`` is given."""

    def __init__(self, percent, height, settings, tint=None):
        Gtk.DrawingArea.__init__(self)
        self.percent = max(0.0, float(percent or 0.0))
        self.settings = settings
        self.tint = tint
        self.set_size_request(-1, height)
        self.set_valign(Gtk.Align.CENTER)
        self.connect("draw", self._draw)

    def _draw(self, widget, cr):
        width = widget.get_allocated_width()
        height = widget.get_allocated_height()
        palette = style.Palette.current()
        ink, alpha = palette.track
        style.rounded_rect(cr, 0, 0, width, height, height / 2.0)
        cr.set_source_rgba(ink[0], ink[1], ink[2], alpha)
        cr.fill()
        if self.percent <= 0:
            return False
        fill = max(height, width * min(1.0, self.percent / 100.0))
        rgb = self.tint or self.settings.usage_color(self.percent)
        style.rounded_rect(cr, 0, 0, fill, height, height / 2.0)
        cr.set_source_rgb(*rgb)
        cr.fill()
        return False


class Mark(Gtk.DrawingArea):
    """A provider's mark in its brand colour (Codex follows the text colour)."""

    def __init__(self, kind, size):
        Gtk.DrawingArea.__init__(self)
        self.kind, self.size = kind, size
        self.set_size_request(size, size)
        self.set_valign(Gtk.Align.CENTER)
        self.connect("draw", self._draw)

    def _draw(self, _widget, cr):
        if cairo is None:
            return False
        rgb = provider_mark.brand_color(self.kind, style.Palette.current().text)
        provider_mark.draw_mark(cr, self.kind, self.size, rgb)
        return False


def _percent_label(percent, css_class, settings, tint=None):
    label = _label("{:.0f}%".format(percent), css_class, xalign=1.0)
    rgb = tint or settings.usage_color(percent)
    # Per-label colour: CSS classes cannot carry the user's thresholds.
    label.set_markup('<span foreground="{}">{:.0f}%</span>'.format(
        "#{:02x}{:02x}{:02x}".format(*(int(c * 255) for c in rgb)), percent))
    return label


class BarRow(Gtk.Box):
    """Name, coloured percentage and optional figure, the bar, then a caption."""

    def __init__(self, name, percent, value_text=None, subtitle=None, settings=None,
                 emphasised=True, tint=None):
        Gtk.Box.__init__(self, orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.settings = settings or Settings.shared()
        percent = max(0.0, float(percent or 0.0))
        head = _hbox(6)
        head.pack_start(_label(name, "tc-name" if emphasised else "tc-name-small", ellipsize=True),
                        True, True, 0)
        if value_text:
            head.pack_end(_label(value_text, "tc-value", xalign=1.0), False, False, 0)
        head.pack_end(_percent_label(percent, "tc-percent" if emphasised else "tc-percent-small",
                                     self.settings, tint), False, False, 0)
        self.pack_start(head, False, False, 0)
        self.pack_start(Bar(percent, 6 if emphasised else 4, self.settings, tint), False, False, 0)
        if subtitle:
            self.pack_start(_label(subtitle, "tc-sub", ellipsize=True), False, False, 0)


class PlaceholderRow(Gtk.Box):
    """A row with no percentage: name, a dash or figure, and a caption."""

    def __init__(self, name, value, subtitle=None, emphasised=True):
        Gtk.Box.__init__(self, orientation=Gtk.Orientation.VERTICAL, spacing=3)
        head = _hbox(6)
        head.pack_start(_label(name, "tc-name" if emphasised else "tc-name-small"), True, True, 0)
        head.pack_end(_label(value, "tc-value", xalign=1.0), False, False, 0)
        self.pack_start(head, False, False, 0)
        if subtitle:
            self.pack_start(_label(subtitle, "tc-sub", wrap=True), False, False, 0)


def _stat_line(name, totals, cost_prefix=""):
    row = _hbox(6)
    row.pack_start(_label(name, "tc-line"), True, True, 0)
    row.pack_end(_label("{} · {}{}".format(Formatting.tokens(totals.total), cost_prefix,
                                           Formatting.usd(totals.cost)), "tc-line", xalign=1.0),
                 False, False, 0)
    return row


def _separator():
    sep = Gtk.Box()
    sep.get_style_context().add_class("tc-sep")
    return sep


def _status_text(data):
    if data.credential_status == STATUS_EXPIRED:
        return "login expired"
    if data.credential_status != STATUS_OK:
        return "not logged in"
    return None


class ProviderCard(Gtk.Box):
    """The rounded card one provider's stats live in, mark in the corner."""

    def __init__(self, data):
        Gtk.Box.__init__(self, orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.get_style_context().add_class("tc-card")
        head = _hbox(7)
        head.pack_start(Mark(data.kind, 16), False, False, 0)
        head.pack_start(_label(data.name, "tc-card-title"), False, False, 0)
        head.pack_start(_spacer(), True, True, 0)
        status = _status_text(data)
        badge_text = status or (data.subscription_type or "").capitalize()
        if badge_text:
            badge = _label(badge_text, "tc-badge")
            if status:
                badge.get_style_context().add_class("tc-warn-badge")
            badge.set_valign(Gtk.Align.CENTER)
            head.pack_end(badge, False, False, 0)
        self.pack_start(head, False, False, 0)

    def put(self, widget):
        self.pack_start(widget, False, False, 0)


def overview_card(data, settings):
    card = ProviderCard(data)
    local = data.local
    primary = data.api.limit(data.primary_limit) if data.api else None
    weekly = data.api.limit("weekly") if data.api else None

    if primary is not None:
        card.put(BarRow(primary.display_name, primary.percent, primary.detail,
                        Formatting.resets_in(primary.resets_at), settings))
    else:
        status = _status_text(data)
        card.put(PlaceholderRow(data.primary_name, "—", status or data.api_error or "no limit data yet"))

    if not data.has_daily:
        pass
    elif local.has_daily_baseline:
        card.put(BarRow("Daily", local.daily_relative_percent,
                        "{} · {}".format(Formatting.tokens(local.today.total), Formatting.usd(local.today.cost)),
                        "vs. busiest day in 30 days", settings))
    else:
        card.put(PlaceholderRow(
            "Daily", "{} · {}".format(Formatting.tokens(local.today.total), Formatting.usd(local.today.cost)),
            "building a 30-day baseline · {} active day{}".format(
                local.active_days_30, "" if local.active_days_30 == 1 else "s")))

    week_figure = "{} · {}".format(Formatting.tokens(local.last7d.total), Formatting.usd(local.last7d.cost))
    if weekly is not None:
        card.put(BarRow("Weekly limit", weekly.percent, week_figure,
                        Formatting.resets_in(weekly.resets_at) or "of your plan's weekly window", settings))
    elif data.has_weekly:
        card.put(BarRow("Weekly", local.weekly_relative_percent, week_figure,
                        "vs. busiest 7-day stretch", settings))

    if data.api is not None and data.api_error:
        card.put(_label(data.api_error, "tc-warn", wrap=True))
    return card


def detailed_card(data, settings):
    card = ProviderCard(data)
    local = data.local
    cost_prefix = "est. " if data.cost_is_estimate else ""

    card.put(_label("PLAN LIMITS", "tc-caption"))
    if data.api is not None and data.api.limits:
        for limit in data.api.limits:
            card.put(BarRow(limit.display_name, limit.percent, limit.detail,
                            Formatting.resets_in(limit.resets_at), settings, emphasised=False))
        if data.api.extra_credits_used is not None:
            card.put(_label("Extra usage credits used: " + Formatting.usd(data.api.extra_credits_used), "tc-sub"))
        card.put(_label("observed " + data.api.fetched_at.astimezone().strftime("%b %d, %H:%M"), "tc-sub"))
        if data.api_error:
            card.put(_label(data.api_error, "tc-warn", wrap=True))
    else:
        status = _status_text(data)
        text = data.api_error or ("{} — run `{}` in a terminal".format(status.capitalize(), data.command)
                                  if status else "Loading…")
        card.put(_label(text, "tc-warn" if status else "tc-note", wrap=True))

    card.put(_separator())
    card.put(_label("TOKEN USAGE (LOCAL)", "tc-caption"))
    if data.has_daily and local.has_daily_baseline:
        card.put(BarRow("Today", local.daily_relative_percent,
                        "{} · {}{}".format(Formatting.tokens(local.today.total), cost_prefix,
                                           Formatting.usd(local.today.cost)),
                        "vs. busiest day in 30 days", settings, emphasised=False))
    else:
        card.put(_stat_line("Today", local.today, cost_prefix))
    for name, totals in (("Last 5 hours", local.last5h), ("Last 7 days", local.last7d),
                         ("Last 30 days", local.last30d), ("All time", local.all_time)):
        card.put(_stat_line(name, totals, cost_prefix))
    t = local.last30d
    card.put(_label("30d: in {} · out {} · cache {}".format(
        Formatting.tokens(t.input), Formatting.tokens(t.output),
        Formatting.tokens(t.cache_create + t.cache_read)), "tc-sub"))

    if local.per_model_30d:
        card.put(_separator())
        card.put(_label("BY MODEL · 30 DAYS", "tc-caption"))
        top = max(1, local.last30d.total)
        accent = style.Palette.current().accent
        for stats in local.per_model_30d[:6]:
            totals = stats.totals
            card.put(BarRow(pretty_model_name(stats.model), totals.total * 100.0 / top,
                            "{} · {}{}".format(Formatting.tokens(totals.total), cost_prefix,
                                               Formatting.usd(totals.cost)),
                            None, settings, emphasised=False, tint=accent))

    if data.account.email or data.rate_limit_tier:
        foot = _hbox(6)
        if data.account.email:
            foot.pack_start(_label(data.account.email, "tc-sub", ellipsize=True), True, True, 0)
        if data.rate_limit_tier:
            foot.pack_end(_label(data.rate_limit_tier, "tc-sub", xalign=1.0), False, False, 0)
        card.put(foot)
    return card


class StatsPanel(PopupWindow):
    """The panel that opens from the tray icon."""

    def __init__(self, state, on_open_settings, on_quit):
        PopupWindow.__init__(self, state.settings)
        self.state = state
        self.on_open_settings = on_open_settings
        self.on_quit = on_quit
        self.detailed = False
        self.set_default_size(PANEL_WIDTH, -1)
        self.set_size_request(PANEL_WIDTH, -1)

        self.root = _vbox(0)
        self.add(self.root)
        self.rebuild()

    # Kept for callers of the previous API.
    def show_panel(self):
        self.popup_at()

    def hide_panel(self):
        self.dismiss()

    def toggle(self):
        self.toggle_at()

    def popup_at(self, root_x=None, root_y=None, anchor_rect=None):
        self.rebuild()
        PopupWindow.popup_at(self, root_x, root_y, anchor_rect)
        self.state.refresh()

    # -- content -----------------------------------------------------------

    def rebuild(self):
        for child in self.root.get_children():
            self.root.remove(child)
            child.destroy()

        header = self._header()
        header.set_margin_start(14)
        header.set_margin_end(10)
        header.set_margin_top(11)
        header.set_margin_bottom(10)
        self.root.pack_start(header, False, False, 0)

        body = _vbox(9)
        body.set_margin_start(12)
        body.set_margin_end(12)
        accounts = self.state.accounts
        if not accounts:
            empty = _vbox(4)
            empty.set_margin_top(18)
            empty.set_margin_bottom(18)
            empty.pack_start(_label("No providers yet", "tc-name", xalign=0.5), False, False, 0)
            empty.pack_start(_label("Run {} in a terminal and log in,\nthen refresh.".format(commands_hint()),
                                    "tc-sub", xalign=0.5), False, False, 0)
            body.pack_start(empty, False, False, 0)
        for data in accounts:
            card = detailed_card(data, self.settings) if self.detailed else overview_card(data, self.settings)
            body.pack_start(card, False, False, 0)

        scroller = Gtk.ScrolledWindow()
        scroller.get_style_context().add_class("tc-scroll")
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_max_content_height(DETAILED_MAX_HEIGHT if self.detailed else OVERVIEW_MAX_HEIGHT)
        scroller.set_propagate_natural_height(True)
        scroller.set_shadow_type(Gtk.ShadowType.NONE)
        scroller.add(body)
        self.root.pack_start(scroller, True, True, 0)

        footer = self._footer()
        footer.set_margin_start(12)
        footer.set_margin_end(10)
        footer.set_margin_top(10)
        footer.set_margin_bottom(10)
        self.root.pack_start(footer, False, False, 0)
        self.root.show_all()
        # Shrink back when switching from Detailed to a shorter Overview.
        self.resize(PANEL_WIDTH, 1)

    def _header(self):
        box = _hbox(8)
        percent = self.state.icon_percent()
        icon = Gtk.DrawingArea()
        icon.set_size_request(16, 16)
        icon.set_valign(Gtk.Align.CENTER)
        icon.connect("draw", self._draw_header_icon)
        box.pack_start(icon, False, False, 0)
        box.pack_start(_label("trackai", "tc-title"), False, False, 0)
        if percent is not None:
            box.pack_start(_percent_label(percent, "tc-percent-small", self.settings), False, False, 0)
        box.pack_start(_spacer(), True, True, 0)
        refresh = self._icon_button("view-refresh-symbolic", "Refresh now",
                                    lambda *_: self.state.refresh(force=True))
        refresh.set_sensitive(not self.state.is_refreshing)
        box.pack_start(refresh, False, False, 0)
        box.pack_start(self._icon_button("system-shutdown-symbolic", "Quit trackai",
                                         lambda *_: self.on_quit()), False, False, 0)
        return box

    def _footer(self):
        box = _hbox(8)
        segments = _hbox(2)
        segments.get_style_context().add_class("tc-segments")
        for title, detailed in (("Overview", False), ("Detailed", True)):
            button = Gtk.Button(label=title)
            button.set_relief(Gtk.ReliefStyle.NONE)
            button.set_can_focus(False)
            ctx = button.get_style_context()
            ctx.add_class("tc-seg")
            if self.detailed == detailed:
                ctx.add_class("tc-selected")
            button.connect("clicked", self._change_page, detailed)
            segments.pack_start(button, False, False, 0)
        segments.set_valign(Gtk.Align.CENTER)
        box.pack_start(segments, False, False, 0)
        box.pack_start(_spacer(), True, True, 0)
        ago = _ago(self.state.last_refresh)
        if self.state.is_refreshing:
            ago = "refreshing…"
        if ago:
            label = _label(ago, "tc-muted", xalign=1.0)
            label.set_valign(Gtk.Align.CENTER)
            box.pack_start(label, False, False, 0)
        box.pack_start(self._icon_button("emblem-system-symbolic", "Settings",
                                         lambda *_: self.on_open_settings()), False, False, 0)
        return box

    def _icon_button(self, icon_name, tooltip, callback):
        button = Gtk.Button.new_from_icon_name(icon_name, Gtk.IconSize.MENU)
        button.set_relief(Gtk.ReliefStyle.NONE)
        button.set_can_focus(False)
        button.set_tooltip_text(tooltip)
        button.set_valign(Gtk.Align.CENTER)
        button.get_style_context().add_class("tc-icon")
        button.connect("clicked", callback)
        return button

    def _draw_header_icon(self, _widget, cr):
        percent = self.state.icon_percent()
        rgb = self.settings.usage_color(percent) if percent is not None else COLOR_GRAY
        status_icon.draw_icon(cr, 16, rgb, self.state.icon_kind(), percent)
        return False

    def _change_page(self, _button, detailed):
        if self.detailed != detailed:
            self.detailed = detailed
            self.rebuild()
