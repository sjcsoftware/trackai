#!/usr/bin/env python3
"""Renders the trackai launcher icon (TrackAI bolt) as PNGs.

Usage: python3 scripts/gen-icon.py <icon-theme-root>

Writes <root>/<size>x<size>/apps/trackai.png for every hicolor size, which
is what .desktop files and GNOME's app grid expect.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from trackai import status_icon   # noqa: E402

SIZES = [16, 32, 48, 64, 128, 256, 512]


def main(argv):
    if len(argv) != 2:
        sys.stderr.write("usage: gen-icon.py <icon-theme-root>\n")
        return 1
    root = os.path.abspath(os.path.expanduser(argv[1]))

    if status_icon.cairo is None:
        sys.stderr.write("gen-icon.py needs pycairo (sudo apt install python3-cairo)\n")
        return 1

    written = 0
    for size in SIZES:
        target_dir = os.path.join(root, "{0}x{0}".format(size), "apps")
        os.makedirs(target_dir, exist_ok=True)
        path = os.path.join(target_dir, "trackai.png")
        if status_icon.write_app_icon(path, size):
            written += 1
        else:
            sys.stderr.write("failed to write {}\n".format(path))
            return 1

    print("wrote {} icons under {}".format(written, root))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
