"""Colours, type and CSS shared by the panel, the hover card and Settings.

The look follows the desktop rather than a fixed brand: the accent comes from
the GTK theme's selection colour, the glass is a dark (or light) neutral
tinted a few percent toward that accent, and text uses Inter when installed,
otherwise the system UI font. Usage colours (green/orange/red) stay semantic.
"""

from __future__ import annotations

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")

from gi.repository import Gdk, Gtk, Pango   # noqa: E402

DEFAULT_ACCENT = (0.29, 0.49, 1.0)
PANEL_RADIUS = 14


def _mix(a, b, t):
    return tuple(a[i] + (b[i] - a[i]) * t for i in range(3))


def _hex(rgb):
    return "#{:02x}{:02x}{:02x}".format(*(int(round(max(0.0, min(1.0, c)) * 255)) for c in rgb))


def _rgba(rgb, alpha):
    return "rgba({}, {}, {}, {:.3f})".format(*(int(round(max(0.0, min(1.0, c)) * 255)) for c in rgb), alpha)


def _luminance(rgb):
    return 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]


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
    if "dark" in theme.lower():
        return True
    # Themes without "dark" in the name: judge by the window background.
    found, color = _lookup("theme_bg_color")
    return bool(found and _luminance((color.red, color.green, color.blue)) < 0.45)


def _lookup(name):
    probe = Gtk.Window()
    try:
        return probe.get_style_context().lookup_color(name)
    finally:
        probe.destroy()


def theme_accent():
    for name in ("accent_bg_color", "theme_selected_bg_color", "selected_bg_color"):
        found, color = _lookup(name)
        if found and color.alpha > 0.5:
            rgb = (color.red, color.green, color.blue)
            # A near-grey selection colour makes a poor accent; keep the default.
            if max(rgb) - min(rgb) > 0.12:
                return rgb
    return DEFAULT_ACCENT


def system_font_family():
    gtk_settings = Gtk.Settings.get_default()
    name = gtk_settings.get_property("gtk-font-name") if gtk_settings else None
    if not name:
        return None
    family = Pango.FontDescription.from_string(name).get_family()
    return family or None


class Palette(object):
    """Resolved once per process: the theme rarely changes under a tray app."""

    _current = None

    @classmethod
    def current(cls):
        if cls._current is None:
            cls._current = cls(prefers_dark(), theme_accent())
        return cls._current

    def __init__(self, dark, accent):
        self.dark = dark
        self.accent = accent
        if dark:
            self.glass = _mix((0.075, 0.086, 0.118), accent, 0.07)
            self.text = (0.902, 0.922, 0.961)
            ink = (1.0, 1.0, 1.0)
        else:
            self.glass = _mix((0.973, 0.976, 0.984), accent, 0.03)
            self.text = (0.094, 0.110, 0.149)
            ink = (0.0, 0.0, 0.0)
        self.ink = ink
        self.edge = (ink, 0.10 if dark else 0.12)
        self.track = (ink, 0.09 if dark else 0.08)
        # Accent text must stay legible on the glass.
        self.accent_text = _mix(accent, (1.0, 1.0, 1.0), 0.35) if dark else _mix(accent, (0, 0, 0), 0.15)


def font_stack():
    families = ["Inter", "Inter Variable"]
    system = system_font_family()
    if system and system not in families:
        families.append(system)
    families.append("sans-serif")
    return ", ".join('"{}"'.format(f) if f != "sans-serif" else f for f in families)


def build_css(p):
    # type: (Palette) -> str
    text = p.text
    ink = p.ink
    return """
.tc-root, .tc-root label, .tc-hover, .tc-hover label {{ font-family: {fonts}; }}
.tc-root label, .tc-hover label {{ color: {text}; }}
.tc-title {{ font-size: 13px; font-weight: 700; }}
.tc-headline {{ font-size: 12px; font-weight: 700; }}
.tc-card {{
    background-color: {card};
    border: 1px solid {card_edge};
    border-radius: 12px;
    padding: 11px 12px 12px 12px;
}}
.tc-card-title {{ font-size: 12.5px; font-weight: 600; }}
.tc-badge {{
    font-size: 10px; font-weight: 600;
    color: {secondary};
    background-color: {badge};
    border-radius: 999px;
    padding: 1px 7px;
}}
.tc-badge.tc-warn-badge {{ color: #ff9f0a; background-color: rgba(255, 159, 10, 0.14); }}
.tc-name {{ font-size: 12px; font-weight: 600; }}
.tc-name-small {{ font-size: 11px; font-weight: 500; }}
.tc-percent {{ font-size: 12px; font-weight: 700; }}
.tc-percent-small {{ font-size: 11px; font-weight: 600; }}
label.tc-value {{ font-size: 10.5px; font-weight: 500; color: {secondary}; }}
label.tc-line {{ font-size: 11px; font-weight: 500; color: {secondary}; }}
label.tc-sub {{ font-size: 10px; font-weight: 500; color: {tertiary}; }}
label.tc-caption {{ font-size: 9.5px; font-weight: 700; color: {tertiary}; }}
label.tc-note {{ font-size: 11px; color: {secondary}; }}
label.tc-warn {{ font-size: 10.5px; font-weight: 500; color: #ff9f0a; }}
label.tc-muted {{ font-size: 10px; font-weight: 500; color: {tertiary}; }}
.tc-sep {{ background-color: {sep}; min-height: 1px; }}

/* Quiet icon buttons and the Overview/Detailed switch, independent of the theme. */
button.tc-icon, button.tc-seg {{
    background: none; background-image: none; border-image: none;
    border: none; box-shadow: none; text-shadow: none; -gtk-icon-shadow: none;
    outline: none; min-height: 0; min-width: 0;
}}
button.tc-icon {{
    padding: 4px; border-radius: 8px; color: {secondary};
    transition: background-color 160ms ease-out, color 160ms ease-out;
}}
button.tc-icon image {{ color: {secondary}; }}
button.tc-icon:hover {{ background-color: {hover}; }}
button.tc-icon:hover image {{ color: {text}; }}
button.tc-icon:active {{ background-color: {press}; }}
button.tc-icon:disabled image {{ color: {tertiary}; }}
.tc-segments {{
    background-color: {track};
    border-radius: 9px;
    padding: 2px;
}}
button.tc-seg {{
    padding: 3px 11px; border-radius: 7px;
    transition: background-color 160ms ease-out;
}}
button.tc-seg label {{ font-size: 11px; font-weight: 600; color: {secondary}; }}
button.tc-seg:hover label {{ color: {text}; }}
button.tc-seg.tc-selected {{ background-color: {accent}; }}
button.tc-seg.tc-selected label {{ color: #ffffff; }}

scrolledwindow.tc-scroll, scrolledwindow.tc-scroll viewport {{ background: none; border: none; }}
scrolledwindow.tc-scroll scrollbar {{ background: none; border: none; }}
scrolledwindow.tc-scroll scrollbar slider {{
    min-width: 4px; min-height: 4px; border-radius: 4px; border: none;
    background-color: {scroll};
}}

/* Tooltips this process shows (buttons, the XEmbed hover card) match the panel. */
tooltip, tooltip.background {{
    background-color: {glass_solid};
    border: 1px solid {card_edge};
    border-radius: 10px;
    box-shadow: none;
    text-shadow: none;
}}
tooltip label {{ color: {text}; font-weight: 500; }}

/* Settings window: grouped cards, same glass family as the panel. */
.tc-settings {{ background-color: {window_bg}; }}
.tc-settings label {{ font-family: {fonts}; }}
.tc-settings .tc-card label.tc-row-label {{ font-size: 12.5px; font-weight: 500; color: {text}; }}
.tc-settings label.tc-section {{
    font-size: 10.5px; font-weight: 700; color: {tertiary}; margin: 0 4px;
}}
""".format(
        fonts=font_stack(),
        text=_hex(text),
        secondary=_rgba(text, 0.66),
        tertiary=_rgba(text, 0.44),
        card=_rgba(ink, 0.05 if p.dark else 0.035),
        card_edge=_rgba(ink, 0.08),
        badge=_rgba(ink, 0.08),
        sep=_rgba(ink, 0.08),
        hover=_rgba(ink, 0.09),
        press=_rgba(ink, 0.15),
        track=_rgba(ink, 0.07),
        scroll=_rgba(ink, 0.22),
        accent=_hex(p.accent),
        glass_solid=_rgba(p.glass, 0.97),
        window_bg=_hex(_mix(p.glass, p.ink, 0.02)),
    )


# GTK releases differ in which CSS properties they know, and one unknown
# property rejects a whole stylesheet; these load separately and may fail.
OPTIONAL_CSS = (
    ".tc-percent, .tc-percent-small, label.tc-value, label.tc-line, label.tc-muted,"
    " .tc-headline { font-feature-settings: \"tnum\"; }",
    "label.tc-caption, label.tc-section { letter-spacing: 0.6px; }",
)

_installed = False


def install_css():
    global _installed
    if _installed:
        return
    screen = Gdk.Screen.get_default()
    if screen is None:
        return
    sheets = [build_css(Palette.current())] + list(OPTIONAL_CSS)
    for sheet in sheets:
        provider = Gtk.CssProvider()
        try:
            provider.load_from_data(sheet.encode())
        except Exception:
            continue
        Gtk.StyleContext.add_provider_for_screen(
            screen, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    _installed = True


def rounded_rect(cr, x, y, width, height, radius):
    import math
    radius = max(0.0, min(radius, width / 2.0, height / 2.0))
    cr.new_sub_path()
    cr.arc(x + width - radius, y + radius, radius, -math.pi / 2, 0)
    cr.arc(x + width - radius, y + height - radius, radius, 0, math.pi / 2)
    cr.arc(x + radius, y + height - radius, radius, math.pi / 2, math.pi)
    cr.arc(x + radius, y + radius, radius, math.pi, 1.5 * math.pi)
    cr.close_path()
