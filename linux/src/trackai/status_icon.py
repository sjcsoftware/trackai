"""The TrackAI tray icon (port of StatusIcon.swift).

The bolt stands for the average across providers and fills from the bottom as
usage climbs; a single or highest reading shows that provider's own mark.
Everything is drawn with cairo, then handed to the tray either as
StatusNotifierItem pixmaps or as a pixbuf for the legacy XEmbed tray, so no
icon files are written or looked up in a theme.

"Show percentage" is drawn into the icon as well, because tray hosts disagree
on labels (eww, KDE, waybar and XEmbed show none). "Under" keeps the icon
square: the glyph moves up and the number sits below it, which every host can
show. "Beside" draws the full-size glyph with "64%" to its right as one wide
pixmap, for hosts that keep a pixmap's aspect ratio; hosts that force icons
square would shrink or squeeze it.
"""

from __future__ import annotations

import math

from . import provider_mark
from .settings import COLOR_GRAY, COLOR_GREEN, COLOR_ORANGE, COLOR_RED

try:
    import cairo
except ImportError:      # rendering is optional; the app falls back to a theme icon
    cairo = None

STATE_COLORS = {
    "gray": COLOR_GRAY,
    "green": COLOR_GREEN,
    "orange": COLOR_ORANGE,
    "red": COLOR_RED,
}

# Every size a tray host is likely to ask for; hosts pick the closest one, so
# each is drawn natively rather than scaled.
PIXMAP_SIZES = (16, 22, 24, 32, 48, 64)

# The bolt in a unit square, y pointing down (StatusIcon.swift, flipped).
BOLT_POINTS = ((0.62, 0.00), (0.18, 0.56), (0.46, 0.56),
               (0.26, 1.00), (0.82, 0.44), (0.54, 0.44))


def _bolt_path(ctx, x, y, w, h):
    ctx.new_path()
    ctx.move_to(x + BOLT_POINTS[0][0] * w, y + BOLT_POINTS[0][1] * h)
    for px, py in BOLT_POINTS[1:]:
        ctx.line_to(x + px * w, y + py * h)
    ctx.close_path()


def draw_bolt(ctx, size, rgb, level=1.0, **_kwargs):
    """The bolt gauge: a faint body, filled from the bottom to ``level`` (0..1)."""
    level = max(0.0, min(1.0, float(level)))
    line = max(1.0, size * 0.09)
    inset = line / 2.0
    box = size - line
    ctx.save()
    _bolt_path(ctx, inset, inset, box, box)
    ctx.set_source_rgba(rgb[0], rgb[1], rgb[2], 0.22)
    ctx.fill_preserve()
    if level > 0:
        ctx.save()
        ctx.clip_preserve()
        ctx.set_source_rgb(*rgb)
        ctx.rectangle(0, inset + box * (1.0 - level), size, box * level + inset)
        ctx.fill()
        ctx.restore()
        _bolt_path(ctx, inset, inset, box, box)
    ctx.set_line_width(line)
    ctx.set_line_join(cairo.LINE_JOIN_ROUND if cairo else 1)
    ctx.set_source_rgb(*rgb)
    ctx.stroke()
    ctx.restore()


def _draw_glyph(ctx, size, rgb, kind, percent):
    if kind is None:
        draw_bolt(ctx, size, rgb, (percent or 0.0) / 100.0)
    else:
        inset = size * 0.06
        provider_mark.draw_mark(ctx, kind, size - inset * 2, rgb, inset, inset)


def _draw_text(ctx, text, rgb, x, y, w, h):
    """``text`` in bold, as large as fits the (x, y, w, h) box, centred."""
    ctx.save()
    ctx.select_font_face("Inter", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
    ctx.set_font_size(h)
    ext = ctx.text_extents(text)
    if ext.width > 0 and ext.height > 0:
        ctx.set_font_size(max(1.0, h * min(w / ext.width, h / ext.height)))
        ext = ctx.text_extents(text)
    ctx.move_to(round(x + (w - ext.width) / 2.0 - ext.x_bearing),
                round(y + (h - ext.height) / 2.0 - ext.y_bearing))
    ctx.set_source_rgb(*rgb)
    ctx.show_text(text)
    ctx.restore()


def percent_text(percent, sign=False):
    # type: (object, bool) -> str
    """The number drawn on the icon; "%" only fits beside it, not under it."""
    text = "{:.0f}".format(max(0.0, min(999.0, float(percent))))
    return text + "%" if sign else text


def draw_icon(ctx, size, rgb, kind=None, percent=None, text=None):
    """The bolt gauge, or ``kind``'s mark inset to the bolt's optical height.

    With ``text`` the glyph shrinks into the top half and the text fills the
    bottom, so the reading shows even on hosts that ignore labels."""
    if not text:
        _draw_glyph(ctx, size, rgb, kind, percent)
        return
    glyph = size * 0.48
    ctx.save()
    ctx.translate((size - glyph) / 2.0, 0)
    _draw_glyph(ctx, glyph, rgb, kind, percent)
    ctx.restore()
    _draw_text(ctx, text, rgb, 0, size * 0.54, size, size * 0.46)


# "Beside": digits as tall as this share of the icon, after a gap of this share.
BESIDE_DIGIT_HEIGHT = 0.5
BESIDE_GAP = 0.2


def _beside_layout(ctx, height, text):
    """Select the font and return [(char, slot width)]. Every digit gets the
    widest digit's slot, so the icon only changes width with the digit count."""
    ctx.select_font_face("Inter", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
    ctx.set_font_size(height)
    zero = ctx.text_extents("0")
    if zero.height > 0:
        ctx.set_font_size(height * height * BESIDE_DIGIT_HEIGHT / zero.height)
    digit = max(ctx.text_extents(d).x_advance for d in "0123456789")
    return [(ch, digit if ch.isdigit() else ctx.text_extents(ch).x_advance) for ch in text]


def beside_width(height, text):
    # type: (int, str) -> int
    """Pixel width of the "beside" icon at ``height``."""
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 1, 1)
    slots = _beside_layout(cairo.Context(surface), height, text)
    return int(math.ceil(height * (1.0 + BESIDE_GAP) + sum(w for _, w in slots)))


def draw_beside(ctx, height, rgb, kind, percent, text):
    """The full-size glyph with ``text`` to its right, vertically centred."""
    _draw_glyph(ctx, height, rgb, kind, percent)
    ctx.save()
    slots = _beside_layout(ctx, height, text)
    digit_height = ctx.text_extents("0").height
    baseline = round((height + digit_height) / 2.0)
    x = height * (1.0 + BESIDE_GAP)
    ctx.set_source_rgb(*rgb)
    for ch, width in slots:
        ext = ctx.text_extents(ch)
        ctx.move_to(round(x + (width - ext.x_advance) / 2.0), baseline)
        ctx.show_text(ch)
        x += width
    ctx.restore()


def render_surface(size, rgb, kind=None, percent=None, text=None):
    """A transparent square surface holding the bolt gauge or a provider mark."""
    if cairo is None:
        return None
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, size, size)
    ctx = cairo.Context(surface)
    draw_icon(ctx, size, rgb, kind, percent, text)
    surface.flush()
    return surface


def render_beside_surface(height, rgb, kind=None, percent=None, text=""):
    """A transparent wide surface: the glyph with ``text`` beside it."""
    if cairo is None:
        return None
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, beside_width(height, text), height)
    ctx = cairo.Context(surface)
    draw_beside(ctx, height, rgb, kind, percent, text)
    surface.flush()
    return surface


def surface_to_argb(surface):
    # type: (object) -> bytes
    """Cairo's native-endian premultiplied pixels to the straight ARGB, network
    byte order, that StatusNotifierItem ``IconPixmap`` requires."""
    width, height = surface.get_width(), surface.get_height()
    stride = surface.get_stride()
    data = bytes(surface.get_data())
    little = __import__("sys").byteorder == "little"
    out = bytearray(width * height * 4)
    o = 0
    for row in range(height):
        base = row * stride
        for col in range(width):
            i = base + col * 4
            if little:
                b, g, r, a = data[i], data[i + 1], data[i + 2], data[i + 3]
            else:
                a, r, g, b = data[i], data[i + 1], data[i + 2], data[i + 3]
            if a and a != 255:
                r = min(255, (r * 255 + a // 2) // a)
                g = min(255, (g * 255 + a // 2) // a)
                b = min(255, (b * 255 + a // 2) // a)
            out[o], out[o + 1], out[o + 2], out[o + 3] = a, r, g, b
            o += 4
    return bytes(out)


_pixmap_cache = {}


def pixmaps(state, kind=None, percent=None, text=None, beside=False):
    """[(width, height, ARGB bytes)] for every tray size; cached per appearance.

    Square unless ``beside`` and ``text`` ask for the wide "beside" layout."""
    if cairo is None:
        return []
    # The bolt's fill is quantised so a refresh only redraws on visible change.
    level = None if kind else int(round(max(0.0, min(100.0, percent or 0.0)) / 5.0)) * 5
    beside = bool(beside and text)
    key = (state, kind, level, text or None, beside)
    cached = _pixmap_cache.get(key)
    if cached is None:
        rgb = STATE_COLORS.get(state, COLOR_GRAY)
        cached = []
        for size in PIXMAP_SIZES:
            if beside:
                surface = render_beside_surface(size, rgb, kind, level, text)
            else:
                surface = render_surface(size, rgb, kind, level, text)
            cached.append((surface.get_width(), size, surface_to_argb(surface)))
        if len(_pixmap_cache) > 64:
            _pixmap_cache.clear()
        _pixmap_cache[key] = cached
    return cached


def pixbuf(size, state, kind=None, percent=None, text=None):
    """A GdkPixbuf for the XEmbed tray fallback, or None without cairo."""
    surface = render_surface(size, STATE_COLORS.get(state, COLOR_GRAY), kind, percent, text)
    if surface is None:
        return None
    from gi.repository import Gdk
    return Gdk.pixbuf_get_from_surface(surface, 0, 0, size, size)


def render_app_icon(size):
    """The launcher icon: dark rounded square with a Claude-orange bolt."""
    if cairo is None:
        return None
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, size, size)
    ctx = cairo.Context(surface)

    inset = size * 0.05
    radius = size * 0.22
    x, y = inset, inset
    w = h = size - inset * 2
    ctx.new_sub_path()
    ctx.arc(x + w - radius, y + radius, radius, -math.pi / 2, 0)
    ctx.arc(x + w - radius, y + h - radius, radius, 0, math.pi / 2)
    ctx.arc(x + radius, y + h - radius, radius, math.pi / 2, math.pi)
    ctx.arc(x + radius, y + radius, radius, math.pi, 1.5 * math.pi)
    ctx.close_path()
    ctx.set_source_rgb(0.122, 0.118, 0.114)
    ctx.fill()

    glyph = size * 0.62
    ctx.translate((size - glyph) / 2.0, (size - glyph) / 2.0)
    draw_bolt(ctx, glyph, (0.851, 0.467, 0.341), 1.0)
    surface.flush()
    return surface


def write_app_icon(path, size):
    # type: (str, int) -> bool
    surface = render_app_icon(size)
    if surface is None:
        return False
    try:
        surface.write_to_png(path)
    except (OSError, IOError):
        return False
    return True
