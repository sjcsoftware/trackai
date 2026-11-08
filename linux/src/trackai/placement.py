"""Where a panel opened from a tray icon goes. Pure arithmetic, tested headlessly."""

from __future__ import annotations

GAP = 6          # between the bar and the panel
MARGIN = 8       # from the monitor edges


def place(size, point, bar, monitor_rect):
    """Top-left corner for a ``size`` panel opened from ``point``.

    ``bar`` is the rectangle of the bar the icon sits in (or None) and
    ``monitor_rect`` the monitor; all in the same coordinate space. The panel
    goes on the far side of the bar from the screen edge it is docked to,
    centred on the click and kept on screen.
    """
    width, height = size
    px, py = point
    mx, my, mw, mh = monitor_rect

    def clamp(value, low, high):
        return max(low, min(value, high))

    if bar is not None:
        bx, by, bw, bh = bar
        if bw >= bh:     # horizontal bar: open below a top bar, above a bottom one
            x = clamp(px - width // 2, mx + MARGIN, mx + mw - width - MARGIN)
            if by + bh / 2.0 < my + mh / 2.0:
                y = by + bh + GAP
            else:
                y = by - height - GAP
        else:            # vertical bar: open to its side
            y = clamp(py - height // 2, my + MARGIN, my + mh - height - MARGIN)
            if bx + bw / 2.0 < mx + mw / 2.0:
                x = bx + bw + GAP
            else:
                x = bx - width - GAP
        return int(clamp(x, mx, mx + mw - width)), int(clamp(y, my, my + mh - height))

    # No bar found: assume the click was at the middle of a bar along the
    # nearest edge, so the panel clears a bar about twice as tall as the offset.
    x = clamp(px - width // 2, mx + MARGIN, mx + mw - width - MARGIN)
    top_gap, bottom_gap = py - my, my + mh - py
    if top_gap <= bottom_gap:
        y = my + max(2 * top_gap, top_gap + 14) + GAP
    else:
        y = my + mh - max(2 * bottom_gap, bottom_gap + 14) - height - GAP
    return int(x), int(clamp(y, my, my + mh - height))
