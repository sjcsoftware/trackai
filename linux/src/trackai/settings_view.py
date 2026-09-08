"""The settings window (port of SettingsView.swift)."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "3.0")

from gi.repository import Gtk, Pango   # noqa: E402

from .providers import PROVIDERS
from .settings import COLOR_METRICS    # noqa: E402
from .stats_view import install_css    # noqa: E402

REFRESH_CHOICES = [("30", "30s", 30.0), ("60", "1m", 60.0), ("120", "2m", 120.0), ("300", "5m", 300.0)]


def _section(title):
    frame = Gtk.Frame(label=title)
    frame.set_label_align(0.02, 0.5)
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    box.set_border_width(12)
    frame.add(box)
    return frame, box


def _row(label_text, widget, expand_widget=False):
    row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
    label = Gtk.Label(label=label_text)
    label.set_xalign(0.0)
    row.pack_start(label, False, False, 0)
    spacer = Gtk.Box()
    spacer.set_hexpand(True)
    row.pack_start(spacer, True, True, 0)
    widget.set_valign(Gtk.Align.CENTER)
    row.pack_end(widget, expand_widget, expand_widget, 0)
    return row


class SettingsWindow(Gtk.Window):
    def __init__(self, state, on_interval_changed):
        Gtk.Window.__init__(self, title="trackai Settings")
        install_css()
        self.state = state
        self.settings = state.settings
        self.on_interval_changed = on_interval_changed
        self._loading = True

        self.set_default_size(460, 640)
        self.set_resizable(True)
        self.connect("delete-event", self._on_delete)

        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        outer.set_border_width(16)
        scroller.add(outer)
        self.add(scroller)

        outer.pack_start(self._menu_bar_section(), False, False, 0)
        outer.pack_start(self._thresholds_section(), False, False, 0)
        outer.pack_start(self._appearance_section(), False, False, 0)
        outer.pack_start(self._general_section(), False, False, 0)
        outer.pack_start(self._providers_section(), False, False, 0)
        outer.pack_start(self._accounts_section(), False, False, 0)

        self._loading = False

    # -- sections ----------------------------------------------------------

    def _menu_bar_section(self):
        frame, box = _section("Tray icon")

        self.metric_combo = Gtk.ComboBoxText()
        for key, label in COLOR_METRICS:
            self.metric_combo.append(key, label)
        self.metric_combo.set_active_id(self.settings.color_metric)
        self.metric_combo.connect("changed", self._on_metric_changed)
        box.pack_start(_row("Icon colour follows", self.metric_combo), False, False, 0)

        self.percent_switch = Gtk.Switch()
        self.percent_switch.set_active(self.settings.show_percent_in_menu_bar)
        self.percent_switch.connect("notify::active", self._on_percent_toggled)
        box.pack_start(_row("Show percentage next to icon", self.percent_switch), False, False, 0)

        mode = Gtk.ComboBoxText()
        for key, title in (("average", "Average"), ("highest", "Highest"), ("single", "Single account")):
            mode.append(key, title)
        mode.set_active_id(self.settings.icon_mode)
        mode.connect("changed", lambda combo: setattr(self.settings, "icon_mode", combo.get_active_id() or "average"))
        box.pack_start(_row("Combine providers", mode), False, False, 0)
        for provider in PROVIDERS:
            check = Gtk.CheckButton(label="Include " + provider.name + " in tray calculation")
            check.set_active(provider.kind in self.settings.icon_providers)
            check.connect("toggled", self._toggle_provider, provider.kind, "icon_providers")
            box.pack_start(check, False, False, 0)
        self.account_combo = Gtk.ComboBoxText()
        self._reload_account_combo()
        self.account_combo.connect("changed", self._on_account_changed)
        self.account_row = _row("Tray icon account", self.account_combo)
        box.pack_start(self.account_row, False, False, 0)
        return frame

    def _thresholds_section(self):
        frame, box = _section("Colour thresholds")

        self.warn_scale, warn_row = self._scale_row(
            "Orange above", self.settings.warn_threshold, 10, 90, 5, self._on_warn_changed)
        box.pack_start(warn_row, False, False, 0)

        self.crit_scale, crit_row = self._scale_row(
            "Red above", self.settings.crit_threshold, 20, 99, 1, self._on_crit_changed)
        box.pack_start(crit_row, False, False, 0)
        return frame

    def _scale_row(self, label_text, value, lower, upper, step, callback):
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        label = Gtk.Label(label=label_text)
        label.set_xalign(0.0)
        label.set_size_request(90, -1)
        row.pack_start(label, False, False, 0)

        scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, lower, upper, step)
        scale.set_value(value)
        scale.set_draw_value(False)
        scale.set_hexpand(True)
        row.pack_start(scale, True, True, 0)

        readout = Gtk.Label(label="{:.0f}%".format(value))
        readout.set_size_request(42, -1)
        readout.set_xalign(1.0)
        readout.get_style_context().add_class("tc-line-value")
        row.pack_end(readout, False, False, 0)

        scale.connect("value-changed", callback, readout)
        return scale, row

    def _appearance_section(self):
        frame, box = _section("Appearance")

        self.opaque_switch = Gtk.Switch()
        self.opaque_switch.set_active(self.settings.opaque_background)
        self.opaque_switch.connect("notify::active", self._on_opaque_toggled)
        box.pack_start(_row("Opaque background", self.opaque_switch), False, False, 0)

        self.transparency_scale = Gtk.Scale.new_with_range(
            Gtk.Orientation.HORIZONTAL, 0.1, 1.0, 0.05)
        self.transparency_scale.set_value(self.settings.transparency)
        self.transparency_scale.set_draw_value(False)
        self.transparency_scale.set_hexpand(True)
        self.transparency_scale.set_sensitive(not self.settings.opaque_background)
        self.transparency_scale.connect("value-changed", self._on_transparency_changed)
        box.pack_start(_row("Transparency", self.transparency_scale, expand_widget=True),
                       False, False, 0)

        hint = Gtk.Label(
            label="Blur behind the panel depends on your compositor; GNOME shows a "
                  "flat translucent panel.")
        hint.set_xalign(0.0)
        hint.set_line_wrap(True)
        hint.get_style_context().add_class("tc-sub")
        box.pack_start(hint, False, False, 0)
        return frame

    def _general_section(self):
        frame, box = _section("General")

        self.launch_switch = Gtk.Switch()
        self.launch_switch.set_active(self.settings.launch_at_login)
        self.launch_switch.connect("notify::active", self._on_launch_toggled)
        box.pack_start(_row("Launch at login", self.launch_switch), False, False, 0)

        self.interval_combo = Gtk.ComboBoxText()
        for key, label, _seconds in REFRESH_CHOICES:
            self.interval_combo.append(key, label)
        self.interval_combo.set_active_id(str(int(self.settings.refresh_interval)))
        if self.interval_combo.get_active_id() is None:
            self.interval_combo.set_active_id("120")
        self.interval_combo.connect("changed", self._on_interval_changed)
        box.pack_start(_row("Refresh every", self.interval_combo), False, False, 0)
        return frame

    def _toggle_provider(self, check, kind, field):
        if self._loading:
            return
        values = list(getattr(self.settings, field))
        values = [v for v in values if v != kind]
        if check.get_active():
            values.append(kind)
        setattr(self.settings, field, values)
        self.state.refresh()

    def _providers_section(self):
        frame, box = _section("Providers")
        self.order_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.pack_start(self.order_box, False, False, 0)
        self._reload_providers()
        home = Gtk.Entry()
        home.set_placeholder_text("$CODEX_HOME or ~/.codex")
        home.set_text(self.settings.codex_home)
        box.pack_start(_row("Codex home", home, True), False, False, 0)
        apply = Gtk.Button(label="Apply Codex path")
        apply.connect("clicked", lambda _button: setattr(self.settings, "codex_home", home.get_text().strip()))
        box.pack_start(apply, False, False, 0)
        return frame

    def _reload_providers(self):
        for child in self.order_box.get_children():
            child.destroy()
        registry = {p.kind: p for p in PROVIDERS}
        for kind in self.settings.provider_order:
            if kind not in registry:
                continue
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            check = Gtk.CheckButton(label=registry[kind].name)
            check.set_active(kind in self.settings.enabled_providers)
            check.connect("toggled", self._toggle_provider, kind, "enabled_providers")
            row.pack_start(check, True, True, 0)
            for label, step in (("↑", -1), ("↓", 1)):
                button = Gtk.Button(label=label)
                button.connect("clicked", self._move_provider, kind, step)
                row.pack_end(button, False, False, 0)
            self.order_box.pack_start(row, False, False, 0)
        self.order_box.show_all()

    def _move_provider(self, _button, kind, step):
        order = list(self.settings.provider_order)
        index = order.index(kind)
        other = index + step
        if 0 <= other < len(order):
            order[index], order[other] = order[other], order[index]
            self.settings.provider_order = order
            self._reload_providers()

    def _accounts_section(self):
        frame, box = _section("Extra Claude accounts")

        self.dirs_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.pack_start(self.dirs_box, False, False, 0)
        self._reload_dirs()

        add_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.dir_entry = Gtk.Entry()
        self.dir_entry.set_placeholder_text("~/.claude-work")
        self.dir_entry.set_hexpand(True)
        self.dir_entry.connect("activate", self._on_add_dir)
        add_row.pack_start(self.dir_entry, True, True, 0)
        add_button = Gtk.Button(label="Add")
        add_button.connect("clicked", self._on_add_dir)
        add_row.pack_end(add_button, False, False, 0)
        box.pack_start(add_row, False, False, 0)

        hint = Gtk.Label(
            label="Add another Claude Code config directory (CLAUDE_CONFIG_DIR) to "
                  "track a second account.")
        hint.set_xalign(0.0)
        hint.set_line_wrap(True)
        hint.get_style_context().add_class("tc-sub")
        box.pack_start(hint, False, False, 0)
        return frame

    # -- dynamic bits ------------------------------------------------------

    def _reload_account_combo(self):
        combo = self.account_combo
        was_loading = self._loading
        self._loading = True
        combo.remove_all()
        combo.append("", "First enabled account")
        for data in self.state.accounts:
            combo.append(data.id, data.label)
        if combo.set_active_id(self.settings.default_account_id) is False:
            combo.set_active_id("")
        self._loading = was_loading

    def _reload_dirs(self):
        for child in self.dirs_box.get_children():
            self.dirs_box.remove(child)
            child.destroy()
        for directory in self.settings.extra_config_dirs:
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            label = Gtk.Label(label=directory)
            label.set_xalign(0.0)
            label.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
            label.get_style_context().add_class("tc-line-value")
            row.pack_start(label, True, True, 0)
            remove = Gtk.Button.new_from_icon_name("list-remove-symbolic", Gtk.IconSize.MENU)
            remove.set_relief(Gtk.ReliefStyle.NONE)
            remove.connect("clicked", self._on_remove_dir, directory)
            row.pack_end(remove, False, False, 0)
            self.dirs_box.pack_start(row, False, False, 0)
        self.dirs_box.show_all()

    def refresh_accounts(self):
        """Called when the account list changes underneath the window."""
        if not self.get_visible():
            return
        self._reload_account_combo()
        self.account_row.set_visible(len(self.state.accounts) > 1)

    # -- handlers ----------------------------------------------------------

    def _on_delete(self, *_args):
        self.hide()
        return True

    def _on_metric_changed(self, combo):
        if self._loading:
            return
        value = combo.get_active_id()
        if value:
            self.settings.color_metric = value

    def _on_percent_toggled(self, switch, _param):
        if self._loading:
            return
        self.settings.show_percent_in_menu_bar = switch.get_active()

    def _on_account_changed(self, combo):
        if self._loading:
            return
        self.settings.default_account_id = combo.get_active_id() or ""

    def _on_warn_changed(self, scale, readout):
        value = round(scale.get_value())
        readout.set_text("{:.0f}%".format(value))
        if self._loading:
            return
        self.settings.warn_threshold = float(min(value, self.settings.crit_threshold))
        scale.set_value(self.settings.warn_threshold)

    def _on_crit_changed(self, scale, readout):
        value = round(scale.get_value())
        readout.set_text("{:.0f}%".format(value))
        if self._loading:
            return
        self.settings.crit_threshold = float(max(value, self.settings.warn_threshold))
        scale.set_value(self.settings.crit_threshold)

    def _on_opaque_toggled(self, switch, _param):
        if self._loading:
            return
        self.settings.opaque_background = switch.get_active()
        self.transparency_scale.set_sensitive(not switch.get_active())

    def _on_transparency_changed(self, scale):
        if self._loading:
            return
        self.settings.transparency = float(scale.get_value())

    def _on_launch_toggled(self, switch, _param):
        if self._loading:
            return
        self.settings.launch_at_login = switch.get_active()

    def _on_interval_changed(self, combo):
        if self._loading:
            return
        active = combo.get_active_id()
        for key, _label, seconds in REFRESH_CHOICES:
            if key == active:
                self.settings.refresh_interval = seconds
                self.on_interval_changed()
                return

    def _on_add_dir(self, *_args):
        trimmed = self.dir_entry.get_text().strip()
        if not trimmed:
            return
        dirs = list(self.settings.extra_config_dirs)
        if trimmed not in dirs:
            dirs.append(trimmed)
            self.settings.extra_config_dirs = dirs
        self.dir_entry.set_text("")
        self._reload_dirs()
        self.state.refresh(force=True)

    def _on_remove_dir(self, _button, directory):
        dirs = [d for d in self.settings.extra_config_dirs if d != directory]
        self.settings.extra_config_dirs = dirs
        self._reload_dirs()
        self.state.refresh(force=True)

    # -- presentation ------------------------------------------------------

    def present_window(self):
        self._reload_account_combo()
        self._reload_dirs()
        self.show_all()
        self.account_row.set_visible(len(self.state.accounts) > 1)
        self.present()
