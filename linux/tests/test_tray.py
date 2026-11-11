"""Panel placement and SNI icon pixels; no display needed."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from trackai.placement import GAP, MARGIN, place  # noqa: E402


class PlacementTests(unittest.TestCase):
    MONITOR = (0, 0, 2560, 1440)

    def test_below_a_top_bar_and_clamped_to_the_right_edge(self):
        x, y = place((340, 300), (2500, 23), (0, 0, 2560, 49), self.MONITOR)
        self.assertEqual(y, 49 + GAP)
        self.assertEqual(x, 2560 - 340 - MARGIN)

    def test_centred_under_the_click_when_room(self):
        x, _ = place((340, 300), (1200, 23), (0, 0, 2560, 49), self.MONITOR)
        self.assertEqual(x, 1200 - 170)

    def test_above_a_bottom_bar(self):
        _, y = place((340, 300), (1200, 1420), (0, 1400, 2560, 40), self.MONITOR)
        self.assertEqual(y, 1400 - 300 - GAP)

    def test_beside_a_vertical_bar(self):
        x, y = place((340, 300), (20, 700), (0, 0, 40, 1440), self.MONITOR)
        self.assertEqual((x, y), (40 + GAP, 700 - 150))
        x, _ = place((340, 300), (2540, 700), (2520, 0, 40, 1440), self.MONITOR)
        self.assertEqual(x, 2520 - 340 - GAP)

    def test_second_monitor_offsets(self):
        x, y = place((340, 300), (2600, 15), (2560, 0, 1920, 30), (2560, 0, 1920, 1080))
        self.assertEqual((x, y), (2560 + MARGIN, 30 + GAP))

    def test_unknown_bar_clears_twice_the_click_offset(self):
        _, y = place((340, 300), (1000, 20), None, self.MONITOR)
        self.assertEqual(y, 40 + GAP)


class PixmapTests(unittest.TestCase):
    def setUp(self):
        from trackai import status_icon
        if status_icon.cairo is None:
            self.skipTest("pycairo not installed")
        self.icon = status_icon

    def test_sni_pixmaps_are_straight_argb_in_network_order(self):
        maps = self.icon.pixmaps("green", "claude")
        self.assertEqual([m[0] for m in maps], list(self.icon.PIXMAP_SIZES))
        for size, height, data in maps:
            self.assertEqual(len(data), size * height * 4)
        # Some fully opaque pixel of the mark carries the exact usage colour.
        size, _, data = maps[-1]
        green = tuple(int(round(c * 255)) for c in self.icon.STATE_COLORS["green"])
        opaque = [tuple(data[i + 1:i + 4]) for i in range(0, len(data), 4) if data[i] == 255]
        self.assertTrue(opaque)
        self.assertTrue(all(abs(a - b) <= 1 for a, b in zip(opaque[0], green)))

    def test_bolt_fill_is_quantised_and_cached(self):
        self.assertIs(self.icon.pixmaps("orange", None, 61), self.icon.pixmaps("orange", None, 59))
        self.assertIsNot(self.icon.pixmaps("orange", None, 20), self.icon.pixmaps("orange", None, 80))

    def test_percentage_is_drawn_into_the_square_icon(self):
        # eww, KDE, waybar and XEmbed show no SNI label, so the number must be
        # in the pixmap itself, and the pixmap must stay square.
        plain = self.icon.pixmaps("green", "codex", 42)
        shown = self.icon.pixmaps("green", "codex", 42, self.icon.percent_text(42))
        other = self.icon.pixmaps("green", "codex", 42, self.icon.percent_text(43))
        for maps in (shown, other):
            self.assertTrue(all(w == h for w, h, _ in maps))
        self.assertNotEqual([m[2] for m in plain], [m[2] for m in shown])
        self.assertNotEqual([m[2] for m in shown], [m[2] for m in other])
        # The number fills the lower half, where the plain glyph leaves rows empty.
        size, _, data = shown[-1]
        lower = data[size * 4 * (size * 3 // 4):]
        self.assertTrue(any(lower[i] for i in range(0, len(lower), 4)))

    def test_percent_text(self):
        self.assertEqual(self.icon.percent_text(7.4), "7")
        self.assertEqual(self.icon.percent_text(99.6), "100")
        self.assertEqual(self.icon.percent_text(-3), "0")


if __name__ == "__main__":
    unittest.main()
