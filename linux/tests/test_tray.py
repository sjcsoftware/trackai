"""Hover summary text, panel placement and SNI icon pixels; no display needed."""
from pathlib import Path
import sys
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from trackai import summary                       # noqa: E402
from trackai.placement import GAP, MARGIN, place  # noqa: E402
from trackai.providers import ProviderSnapshot    # noqa: E402
from trackai.settings import Settings             # noqa: E402
from trackai.usage_api import ApiUsage, LimitInfo  # noqa: E402

NOW = datetime.now(timezone.utc)


def snapshot(kind="claude", name="Claude Code", session=None, weekly=None, error=None,
             status="ok", fetched=NOW):
    data = ProviderSnapshot(kind, name, "/fixture/" + kind)
    data.credential_status = status
    limits = []
    if session is not None:
        limits.append(LimitInfo("session", "session", session, NOW + timedelta(hours=1, minutes=30)))
    if weekly is not None:
        limits.append(LimitInfo("weekly", "weekly", weekly, NOW + timedelta(days=2)))
    if limits:
        data.api = ApiUsage(limits, None, fetched)
    data.api_error = error
    return data


class SummaryTests(unittest.TestCase):
    def setUp(self):
        self.settings = Settings.__new__(Settings)
        self.settings._values = {"warnThreshold": 50.0, "critThreshold": 80.0}
        self.settings._listeners = []

    def line(self, data):
        return summary.provider_line(data, self.settings)

    def test_both_limits_without_reset_below_warning(self):
        self.assertEqual(self.line(snapshot(session=12, weekly=40)), "Claude Code — 5h 12% · week 40%")

    def test_reset_time_appears_once_session_is_high(self):
        text = self.line(snapshot(session=72.4, weekly=40))
        self.assertTrue(text.startswith("Claude Code — 5h 72% (resets 1h "), text)
        self.assertTrue(text.endswith(") · week 40%"), text)

    def test_stale_codex_limits_say_how_old(self):
        old = NOW - timedelta(hours=8)
        data = snapshot("codex", "Codex", 10, 3, "Limits as of the last Codex run (over 6 hours old)",
                        fetched=old)
        self.assertTrue(self.line(data).endswith("· as of " + old.astimezone().strftime("%H:%M")))

    def test_no_limits_falls_back_to_login_state_or_local_usage(self):
        self.assertEqual(self.line(snapshot(status="expired")), "Claude Code — login expired")
        self.assertEqual(self.line(snapshot(status="missing")), "Claude Code — not logged in")
        self.assertEqual(self.line(snapshot()), "Claude Code — no usage yet")

    def test_tooltip_has_one_line_per_provider(self):
        title, body = summary.tooltip([snapshot(session=1, weekly=2),
                                       snapshot("codex", "Codex", 3, 4)], self.settings)
        self.assertEqual(title, "trackai")
        self.assertEqual(body.splitlines(), ["Claude Code — 5h 1% · week 2%", "Codex — 5h 3% · week 4%"])
        self.assertIn("log in", summary.tooltip([], self.settings)[1])

    def test_label(self):
        self.assertEqual(summary.label(None), "")
        self.assertEqual(summary.label(41.6), "42%")


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


if __name__ == "__main__":
    unittest.main()
