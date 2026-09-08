"""Unit tests for the platform-independent core.

Run with:  python3 -m unittest discover -s tests -v
No third-party dependencies; GTK is never imported here.
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from trackai import pricing, usage_api                      # noqa: E402
from trackai.credentials import parse_credentials           # noqa: E402
from trackai.transcripts import (                           # noqa: E402
    Formatting, TranscriptScanner, parse_iso8601,
)


class PricingTests(unittest.TestCase):
    def test_tiers(self):
        self.assertEqual(pricing.pricing("claude-opus-4-5-20251101").input, 5)
        self.assertEqual(pricing.pricing("claude-opus-4-1-20250805").input, 15)
        self.assertEqual(pricing.pricing("claude-fable-5").output, 50)
        self.assertEqual(pricing.pricing("claude-haiku-3-5").input, 0.8)
        self.assertEqual(pricing.pricing("claude-haiku-3").input, 0.25)
        self.assertEqual(pricing.pricing("claude-haiku-4-5-20251001").input, 1)
        # Unknown models fall back to Sonnet-tier pricing.
        self.assertEqual(pricing.pricing("something-new").input, 3)

    def test_cost(self):
        # 1M input on Sonnet pricing is exactly $3.
        self.assertAlmostEqual(pricing.cost("claude-sonnet-5", 1_000_000, 0, 0, 0), 3.0)
        self.assertAlmostEqual(pricing.cost("claude-sonnet-5", 0, 0, 0, 1_000_000), 0.3)

    def test_pretty_names(self):
        self.assertEqual(pricing.pretty_model_name("claude-opus-4-5-20251101"), "Opus 4.5")
        self.assertEqual(pricing.pretty_model_name("claude-opus-5"), "Opus 5")
        self.assertEqual(pricing.pretty_model_name("claude-haiku-4-5-20251001"), "Haiku 4.5")
        self.assertEqual(pricing.pretty_model_name("claude-sonnet-5"), "Sonnet 5")


class TimestampTests(unittest.TestCase):
    def test_variants(self):
        cases = [
            "2026-08-07T10:11:12Z",
            "2026-08-07T10:11:12.123Z",
            "2026-08-07T10:11:12.123456789Z",
            "2026-08-07T10:11:12+00:00",
            "2026-08-07T19:11:12+0900",
        ]
        for text in cases:
            parsed = parse_iso8601(text)
            self.assertIsNotNone(parsed, text)
            self.assertEqual(parsed.astimezone(timezone.utc).hour, 10, text)

    def test_rejects_garbage(self):
        for text in ("", "not-a-date", "2026-13-99T99:99:99Z"):
            self.assertIsNone(parse_iso8601(text))


class FormattingTests(unittest.TestCase):
    def test_tokens(self):
        self.assertEqual(Formatting.tokens(999), "999")
        self.assertEqual(Formatting.tokens(1500), "1.5K")
        self.assertEqual(Formatting.tokens(2_500_000), "2.5M")
        self.assertEqual(Formatting.tokens(3_250_000_000), "3.25B")

    def test_usd(self):
        self.assertEqual(Formatting.usd(1.234), "$1.23")
        self.assertEqual(Formatting.usd(42.7), "$43")

    def test_resets_in(self):
        now = datetime.now(timezone.utc)
        self.assertEqual(Formatting.resets_in(now + timedelta(minutes=30, seconds=1)),
                         "resets in 30m")
        self.assertEqual(Formatting.resets_in(now + timedelta(hours=3, minutes=5, seconds=1)),
                         "resets in 3h 5m")
        self.assertTrue(Formatting.resets_in(now + timedelta(hours=50)).startswith("resets in 2d"))
        self.assertIsNone(Formatting.resets_in(now - timedelta(hours=1)))
        self.assertIsNone(Formatting.resets_in(None))


class UsageAPIParseTests(unittest.TestCase):
    def test_limits_schema(self):
        payload = json.dumps({
            "limits": [
                {"kind": "session", "group": "session", "percent": 42,
                 "resets_at": "2026-08-07T15:00:00Z", "is_active": True},
                {"kind": "weekly_all", "group": "weekly", "percent": 13.5,
                 "resets_at": "2026-08-11T15:00:00.500Z"},
            ],
            "extra_usage": {"used_credits": 1250, "decimal_places": 2},
        }).encode("utf-8")
        usage = usage_api.parse(payload)
        self.assertIsNotNone(usage)
        self.assertEqual(len(usage.limits), 2)
        self.assertEqual(usage.limits[0].display_name, "Session (5h)")
        self.assertEqual(usage.limits[0].percent, 42.0)
        self.assertEqual(usage.limits[1].display_name, "Weekly (all models)")
        self.assertIsNotNone(usage.limits[0].resets_at)
        self.assertAlmostEqual(usage.extra_credits_used, 12.5)
        self.assertIsNotNone(usage.limit("weekly"))
        self.assertIsNone(usage.limit("nope"))

    def test_legacy_schema_fallback(self):
        payload = json.dumps({
            "five_hour": {"utilization": 61, "resets_at": "2026-08-07T15:00:00Z"},
            "seven_day": {"utilization": 22},
        }).encode("utf-8")
        usage = usage_api.parse(payload)
        kinds = [l.kind for l in usage.limits]
        self.assertEqual(kinds, ["session", "weekly_all"])
        self.assertEqual(usage.limits[0].percent, 61.0)

    def test_bad_payloads(self):
        self.assertIsNone(usage_api.parse(b"not json"))
        self.assertIsNone(usage_api.parse(b"[1, 2, 3]"))

    def test_roundtrip(self):
        usage = usage_api.ApiUsage(
            limits=[usage_api.LimitInfo("session", "session", 42.0,
                                        datetime.now(timezone.utc), True)],
            extra_credits_used=3.5,
            fetched_at=datetime.now(timezone.utc),
        )
        restored = usage_api.ApiUsage.from_dict(json.loads(json.dumps(usage.to_dict())))
        self.assertIsNotNone(restored)
        self.assertEqual(restored.limits[0].kind, "session")
        self.assertEqual(restored.limits[0].percent, 42.0)
        self.assertAlmostEqual(restored.extra_credits_used, 3.5)
        self.assertAlmostEqual(
            (restored.fetched_at - usage.fetched_at).total_seconds(), 0.0, places=3)

    def test_error_descriptions(self):
        self.assertEqual(usage_api.UsageAPIError("http", code=401).description,
                         "unauthorized (token expired?)")
        self.assertEqual(usage_api.UsageAPIError("http", code=503).description, "HTTP 503")
        self.assertIn("rate limited", usage_api.UsageAPIError("rate_limited").description)


class CredentialsTests(unittest.TestCase):
    def test_wrapped_and_bare(self):
        expires_ms = (datetime.now(timezone.utc) + timedelta(hours=2)).timestamp() * 1000
        wrapped = json.dumps({"claudeAiOauth": {
            "accessToken": "tok", "expiresAt": expires_ms,
            "subscriptionType": "max", "rateLimitTier": "default_max_20x",
        }}).encode("utf-8")
        creds = parse_credentials(wrapped)
        self.assertEqual(creds.access_token, "tok")
        self.assertEqual(creds.subscription_type, "max")
        self.assertFalse(creds.is_expired)

        bare = json.dumps({"accessToken": "tok2"}).encode("utf-8")
        self.assertEqual(parse_credentials(bare).access_token, "tok2")

    def test_expiry(self):
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).timestamp() * 1000
        creds = parse_credentials(json.dumps({"accessToken": "t", "expiresAt": past}).encode())
        self.assertTrue(creds.is_expired)

    def test_rejects_junk(self):
        self.assertIsNone(parse_credentials(b"{}"))
        self.assertIsNone(parse_credentials(b"nope"))
        self.assertIsNone(parse_credentials(json.dumps({"accessToken": ""}).encode()))


class ScannerTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="trackai-test-")
        self.projects = os.path.join(self.dir, "projects", "demo")
        os.makedirs(self.projects)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def _write(self, name, records):
        path = os.path.join(self.projects, name)
        with open(path, "w", encoding="utf-8") as fh:
            for record in records:
                fh.write(json.dumps(record) + "\n")
        return path

    @staticmethod
    def _record(msg_id, when, model="claude-sonnet-5", req="req-1",
                inp=10, out=20, cc=30, cr=40):
        return {
            "type": "assistant",
            "requestId": req,
            "timestamp": when.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            "message": {
                "id": msg_id,
                "model": model,
                "usage": {
                    "input_tokens": inp, "output_tokens": out,
                    "cache_creation_input_tokens": cc, "cache_read_input_tokens": cr,
                },
            },
        }

    def test_windows_and_dedup(self):
        now = datetime.now(timezone.utc)
        self._write("a.jsonl", [
            self._record("m1", now - timedelta(minutes=5)),
            # Same message id + request id written twice by streaming: counts once.
            self._record("m1", now - timedelta(minutes=5)),
            self._record("m2", now - timedelta(hours=8)),          # today (if late enough) / 7d
            self._record("m3", now - timedelta(days=10)),          # 30d only
            self._record("m4", now - timedelta(days=90)),          # all time only
            # Ignored records:
            {"type": "user", "timestamp": now.isoformat(), "message": {}},
            self._record("m5", now, model="<synthetic>"),
            self._record("m6", now, inp=0, out=0, cc=0, cr=0),
            {"type": "assistant", "message": {"model": "claude-sonnet-5"}},   # no usage
        ])
        stats = TranscriptScanner().scan(self.dir)

        self.assertEqual(stats.all_time.messages, 4)
        self.assertEqual(stats.last30d.messages, 3)
        self.assertEqual(stats.last7d.messages, 2)
        self.assertEqual(stats.last5h.messages, 1)
        self.assertEqual(stats.last5h.total, 100)
        self.assertEqual(stats.all_time.total, 400)
        self.assertEqual([m.model for m in stats.per_model], ["claude-sonnet-5"])
        self.assertGreater(stats.daily_peak_30, 0)
        self.assertLessEqual(stats.daily_relative_percent, 100.0)

    def test_model_ordering_and_cache_invalidation(self):
        now = datetime.now(timezone.utc)
        path = self._write("b.jsonl", [
            self._record("m1", now, model="claude-sonnet-5", inp=1, out=1, cc=1, cr=1),
            self._record("m2", now, model="claude-opus-5", req="r2",
                         inp=100, out=100, cc=100, cr=100),
        ])
        scanner = TranscriptScanner()
        stats = scanner.scan(self.dir)
        self.assertEqual([m.model for m in stats.per_model], ["claude-opus-5", "claude-sonnet-5"])

        # A rescan with no changes must reuse the cache and give the same answer.
        self.assertEqual(scanner.scan(self.dir).all_time.total, stats.all_time.total)

        # Appending invalidates the (mtime, size) cache key.
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(self._record("m3", now, req="r3")) + "\n")
        os.utime(path, (now.timestamp() + 10, now.timestamp() + 10))
        self.assertEqual(scanner.scan(self.dir).all_time.messages, 3)

    def test_missing_directory(self):
        stats = TranscriptScanner().scan(os.path.join(self.dir, "nope"))
        self.assertEqual(stats.all_time.messages, 0)
        self.assertEqual(stats.daily_relative_percent, 0.0)


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="trackai-cfg-")
        self._env = {k: os.environ.get(k) for k in ("XDG_CONFIG_HOME", "XDG_CACHE_HOME")}
        os.environ["XDG_CONFIG_HOME"] = os.path.join(self.dir, "config")
        os.environ["XDG_CACHE_HOME"] = os.path.join(self.dir, "cache")
        for name in list(sys.modules):
            if name.startswith("trackai.settings"):
                del sys.modules[name]

    def tearDown(self):
        for key, value in self._env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        shutil.rmtree(self.dir, ignore_errors=True)
        for name in list(sys.modules):
            if name.startswith("trackai.settings"):
                del sys.modules[name]

    def test_roundtrip_and_colors(self):
        import importlib
        settings_mod = importlib.import_module("trackai.settings")
        settings = settings_mod.Settings()

        self.assertEqual(settings.warn_threshold, 50.0)
        self.assertEqual(settings.color_metric, settings_mod.METRIC_DAILY)

        settings.warn_threshold = 40.0
        settings.crit_threshold = 80.0
        settings.extra_config_dirs = ["~/.claude-work"]
        settings.opaque_background = True

        reloaded = settings_mod.Settings()
        self.assertEqual(reloaded.warn_threshold, 40.0)
        self.assertEqual(reloaded.extra_config_dirs, ["~/.claude-work"])
        self.assertEqual(reloaded.panel_alpha, 1.0)

        self.assertEqual(reloaded.usage_color_name(10), "green")
        self.assertEqual(reloaded.usage_color_name(50), "orange")
        self.assertEqual(reloaded.usage_color_name(95), "red")

        reloaded.opaque_background = False
        reloaded.transparency = 0.65
        self.assertTrue(0.35 <= reloaded.panel_alpha < 1.0)

    def test_ignores_corrupt_file(self):
        import importlib
        settings_mod = importlib.import_module("trackai.settings")
        settings_mod.ensure_dir(settings_mod.CONFIG_DIR)
        with open(settings_mod.SETTINGS_FILE, "w", encoding="utf-8") as fh:
            fh.write("{not json")
        self.assertEqual(settings_mod.Settings().warn_threshold, 50.0)

    def test_listeners(self):
        import importlib
        settings_mod = importlib.import_module("trackai.settings")
        settings = settings_mod.Settings()
        seen = []
        settings.add_listener(lambda: seen.append(1))
        settings.show_percent_in_menu_bar = True
        settings.show_percent_in_menu_bar = True      # no-op, must not notify twice
        self.assertEqual(len(seen), 1)


class StateTests(unittest.TestCase):
    def test_metric_selection(self):
        from trackai.credentials import Account
        from trackai.providers import ProviderSnapshot
        from trackai.transcripts import LocalStats

        data = ProviderSnapshot("claude", "Claude Code", "/tmp/x")
        local = LocalStats()
        local.daily_peak_30 = 100
        local.active_days_30 = 3
        local.today.input = 25
        data.local = local
        data.api = usage_api.ApiUsage(
            limits=[
                usage_api.LimitInfo("session", "session", 42.0, None, True),
                usage_api.LimitInfo("weekly_all", "weekly", 66.0, None, True),
            ],
            extra_credits_used=None,
            fetched_at=datetime.now(timezone.utc),
        )
        self.assertEqual(data.metric_percent("daily"), 25.0)
        self.assertEqual(data.metric_percent("session"), 42.0)
        self.assertEqual(data.metric_percent("weekly"), 66.0)

        empty = ProviderSnapshot("claude", "Claude Code", "/tmp/y")
        self.assertIsNone(empty.metric_percent("session"))
        self.assertIsNone(empty.metric_percent("daily"))


if __name__ == "__main__":
    unittest.main()
