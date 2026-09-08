"""The TrackAI bolt tray icon (port of StatusIcon.swift).

AppIndicator/StatusNotifierItem can only show an icon it can load from a
theme directory, so each colour state is rendered once with cairo into
``$XDG_CACHE_HOME/trackai/icons`` and referenced by name.
"""

from __future__ import annotations

import math
import os

from .settings import COLOR_GRAY, COLOR_GREEN, COLOR_ORANGE, COLOR_RED, ICON_DIR, ensure_dir

try:
    import cairo
except ImportError:      # rendering is optional; the app falls back to a theme icon
    cairo = None

# Slightly irregular ray lengths for the organic Claude-logo feel.
RAY_LENGTHS = [1.0, 0.78, 0.95, 0.8, 1.0, 0.78, 0.95, 0.8, 1.0, 0.78]
RAY_COUNT = 10

STATE_COLORS = {
    "gray": COLOR_GRAY,
    "green": COLOR_GREEN,
    "orange": COLOR_ORANGE,
    "red": COLOR_RED,
}

TRAY_SIZE = 22
ICON_NAME_PREFIX = "trackai-"


def draw_bolt(ctx, size, rgb, **_kwargs):
    """TrackAI's bolt, drawn directly with Cairo; no external image assets."""
    ctx.save()
    ctx.set_source_rgb(*rgb)
    points = ((0.59, 0.06), (0.20, 0.55), (0.46, 0.55),
              (0.36, 0.94), (0.81, 0.40), (0.54, 0.40))
    ctx.move_to(points[0][0] * size, points[0][1] * size)
    for x, y in points[1:]:
        ctx.line_to(x * size, y * size)
    ctx.close_path()
    ctx.fill()
    ctx.restore()


def render_surface(size, rgb):
    """Render a transparent square surface holding the bolt."""
    if cairo is None:
        return None
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, size, size)
    ctx = cairo.Context(surface)
    draw_bolt(ctx, size, rgb)
    surface.flush()
    return surface


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

    draw_bolt(ctx, size, (0.851, 0.467, 0.341),
                   outer_scale=0.33, inner_scale=0.08, width_scale=0.085)
    surface.flush()
    return surface


def icon_name(state):
    # type: (str) -> str
    return ICON_NAME_PREFIX + state


def ensure_tray_icons(size=TRAY_SIZE):
    # type: (int) -> "str | None"
    """Render every colour state into the icon theme dir. Returns that dir."""
    if cairo is None:
        return None
    ensure_dir(ICON_DIR)
    for state, rgb in STATE_COLORS.items():
        # Always re-render: it costs microseconds and keeps an upgraded build
        # from showing the previous version's cached artwork.
        path = os.path.join(ICON_DIR, icon_name(state) + ".png")
        surface = render_surface(size, rgb)
        if surface is None:
            return None
        try:
            surface.write_to_png(path)
        except (OSError, IOError):
            return None
    return ICON_DIR


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
