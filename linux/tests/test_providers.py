"""Regression tests for Codex accounting and cross-process Claude throttling."""
import base64
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from trackai.codex import CodexSessionScanner, read_account, parse_limits, cost
from trackai.providers import ClaudeLimitCache, CodexProvider, ProviderSnapshot, collect
from trackai.settings import Settings
from trackai.state import AppState
from trackai.transcripts import TranscriptScanner, UsageEntry
from trackai.usage_api import ApiUsage, LimitInfo, UsageAPIError

NOW = datetime.now(timezone.utc) - timedelta(seconds=1)


def event(kind, payload, when=NOW):
    return {"type": kind, "timestamp": when.isoformat(), "payload": payload}


def usage(inp=100, cached=60, out=20):
    return {"input_tokens": inp, "cached_input_tokens": cached,
            "output_tokens": out, "reasoning_output_tokens": 10}


class CodexTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        (self.home / "sessions").mkdir()
        self.scanner = CodexSessionScanner()

    def write(self, name, rows):
        path = self.home / "sessions" / name
        path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
        return path

    def record(self, response="r1"):
        return event("token_usage_record", {"response_id": response, "usage": usage()})

    def old(self):
        return event("event_msg", {"type": "token_count", "info": {"last_token_usage": usage()}})

    def test_new_format_dedup_and_inclusive_tokens(self):
        rows = [event("turn_context", {"model": "gpt-5.5"}), self.record(), self.record()]
        self.write("one.jsonl", rows)
        self.write("copied.jsonl", rows)
        stats, _ = self.scanner.scan(self.home)
        self.assertEqual(stats.all_time.messages, 1)
        self.assertEqual((stats.all_time.input, stats.all_time.cache_read, stats.all_time.output), (40, 60, 20))
        self.assertEqual(stats.all_time.total, 120)
        self.assertAlmostEqual(stats.all_time.cost, cost("gpt-5.5", 40, 20, 0, 60))

    def test_old_format_null_info_and_deltas(self):
        self.write("old.jsonl", [event("session_meta", {"model": "gpt-5-mini"}),
                                 event("event_msg", {"type": "token_count", "info": None}),
                                 self.old(), self.old()])
        stats, _ = self.scanner.scan(self.home)
        self.assertEqual(stats.all_time.total, 240)
        self.assertEqual(stats.all_time.messages, 2)
        self.assertEqual(stats.per_model[0].model, "gpt-5-mini")

    def test_mixed_format_never_counts_twice(self):
        self.write("mixed.jsonl", [self.old(), self.record()])
        self.assertEqual(self.scanner.scan(self.home)[0].all_time.total, 120)

    def test_zero_or_malformed_record_still_suppresses_events(self):
        for payload in ({"usage": {}}, {"usage": None}, {}):
            self.write("mixed.jsonl", [self.old(), event("token_usage_record", payload)])
            self.assertEqual(self.scanner.scan(self.home)[0].all_time.total, 0)

    def test_latest_limits_across_files_and_record_types(self):
        def limits(percent):
            return {"primary": {"used_percent": percent, "window_minutes": 300,
                                "resets_in_seconds": 60}, "plan_type": "plus"}
        self.write("a.jsonl", [event("event_msg", {"rate_limits": limits(10)}, NOW - timedelta(days=1))])
        self.write("b.jsonl", [event("token_usage_record", {"usage": usage(), "rate_limits": limits(42)})])
        _, latest = self.scanner.scan(self.home)
        self.assertEqual(latest[0].limits[0].percent, 42)
        self.assertEqual(latest[0].limits[0].display_name, "Session (5h)")
        self.assertEqual(latest[0].limits[0].resets_at, NOW + timedelta(seconds=60))
        self.assertEqual(latest[1], "plus")

    def test_limit_without_timestamp_is_not_presented_as_fresh(self):
        self.write("a.jsonl", [{"type": "event_msg", "payload": {"rate_limits": {"primary": {"used_percent": 20}}}}])
        self.assertIsNone(self.scanner.scan(self.home)[1])

    def test_append_truncate_and_delete_invalidate_cache(self):
        path = self.write("a.jsonl", [self.record()])
        self.assertEqual(self.scanner.scan(self.home)[0].all_time.messages, 1)
        with path.open("a") as stream:
            stream.write(json.dumps(self.record("r2")) + "\n")
        self.assertEqual(self.scanner.scan(self.home)[0].all_time.messages, 2)
        path.write_text("")
        self.assertEqual(self.scanner.scan(self.home)[0].all_time.messages, 0)
        path.unlink()
        self.scanner.scan(self.home)
        self.assertFalse(self.scanner._cache)

    def test_partial_and_unexpected_json_records_are_ignored(self):
        path = self.write("a.jsonl", [None, [], {}, event("token_usage_record", {"usage": []}), self.record()])
        with path.open("a") as stream:
            stream.write('{"unfinished":')
        self.assertEqual(self.scanner.scan(self.home)[0].all_time.messages, 1)

    def test_model_changes_and_cache_write_split(self):
        self.write("a.jsonl", [event("session_meta", {"model": "gpt-5-mini"}), self.record(),
                                 event("turn_context", {"model": "gpt-5.5"}),
                                 event("token_usage_record", {"response_id": "r2", "usage": dict(usage(), cache_write_input_tokens=10)})])
        stats, _ = self.scanner.scan(self.home)
        self.assertEqual(len(stats.per_model), 2)
        self.assertEqual(stats.all_time.total, 240)
        self.assertEqual(stats.all_time.cache_create, 10)

    def test_auth_jwt_expiry_api_key_and_malformed(self):
        claims = {"email": "test@example.invalid", "exp": 1,
                  "https://api.openai.com/auth": {"chatgpt_plan_type": "plus"}}
        payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
        auth = self.home / "auth.json"
        auth.write_text(json.dumps({"tokens": {"id_token": "header." + payload + ".signature"}}))
        self.assertEqual(read_account(self.home)["plan"], "plus")
        auth.write_text(json.dumps({"OPENAI_API_KEY": "fixture", "auth_mode": "apikey"}))
        self.assertEqual(read_account(self.home)["plan"], "apikey")
        for obj in ([], {}, {"tokens": []}, {"tokens": {"id_token": "invalid"}}):
            auth.write_text(json.dumps(obj))
            self.assertIsNone(read_account(self.home))

    def test_codex_is_offline_and_labels_stale_limits(self):
        self.write("a.jsonl", [event("event_msg", {"rate_limits": {"secondary": {"used_percent": 20}}}, NOW - timedelta(hours=7))])
        settings = Settings().snapshot()
        settings._values["codexHome"] = str(self.home)
        with patch("urllib.request.urlopen", side_effect=AssertionError("Codex attempted network")):
            data = CodexProvider().scan(settings)[0]
        self.assertIn("last Codex run", data.api_error)
        self.assertLess(data.api.fetched_at, NOW - timedelta(hours=6))


class CacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.now = 1000000.0
        self.calls = []
        self.error = None
        self.cache = ClaudeLimitCache(self.tmp.name, self.fetch, lambda: self.now)

    def fetch(self, token):
        self.calls.append(token)
        if self.error:
            raise self.error
        return ApiUsage([LimitInfo("session", "session", 42, None)], None,
                        datetime.fromtimestamp(self.now, timezone.utc))

    def test_five_minute_floor_and_persisted_cache(self):
        self.cache.get("fixture-token")
        self.now += 299
        other = ClaudeLimitCache(self.tmp.name, self.fetch, lambda: self.now)
        self.assertEqual(other.get("fixture-token")[0].limits[0].percent, 42)
        self.assertEqual(len(self.calls), 1)
        self.now += 1
        other.get("fixture-token")
        self.assertEqual(len(self.calls), 2)
        for path in Path(self.tmp.name).iterdir():
            self.assertNotIn("fixture-token", path.name + path.read_text())

    def test_manual_floor_and_separate_tokens(self):
        self.cache.get("one")
        self.now += 59
        self.cache.get("one", True)
        self.assertEqual(len(self.calls), 1)
        self.now += 1
        self.cache.get("one", True)
        self.cache.get("two", True)
        self.assertEqual(len(self.calls), 3)

    def test_exponential_backoff_survives_restart_and_keeps_good_data(self):
        self.cache.get("one")
        self.now += 301
        self.error = UsageAPIError("rate_limited", retry_after=400)
        self.assertIsNotNone(self.cache.get("one")[0])
        self.now += 399
        other = ClaudeLimitCache(self.tmp.name, self.fetch, lambda: self.now)
        other.get("one", True)
        self.assertEqual(len(self.calls), 2)
        self.now += 1
        other.get("one", True)
        self.assertEqual(len(self.calls), 3)
        self.now += 599
        other.get("one", True)
        self.assertEqual(len(self.calls), 3)
        self.now += 1
        self.error = None
        self.assertIsNone(other.get("one", True)[1])
        self.assertEqual(len(self.calls), 4)

    def test_failed_requests_also_respect_normal_floor(self):
        self.error = UsageAPIError("http", code=503)
        self.cache.get("one")
        self.now += 299
        self.cache.get("one")
        self.assertEqual(len(self.calls), 1)


class ProviderStateTests(unittest.TestCase):
    def test_baselines_and_future_records(self):
        records = [UsageEntry(str(i), "claude-sonnet-5", NOW - timedelta(days=i), 10, 0, 0, 0) for i in range(3)]
        scanner = TranscriptScanner()
        self.assertFalse(scanner._aggregate(records[:1]).has_daily_baseline)
        stats = scanner._aggregate(records)
        self.assertTrue(stats.has_daily_baseline)
        self.assertEqual(stats.weekly_relative_percent, 100)
        future = UsageEntry("future", "claude-sonnet-5", NOW + timedelta(days=2), 100, 0, 0, 0)
        self.assertEqual(scanner._aggregate(records + [future]).all_time.total, 30)

    def test_average_highest_single_and_unknown_daily(self):
        settings = Settings().snapshot()
        settings._values.update(colorMetric="session", iconMode="average", iconProviders=["claude", "codex"])
        state = AppState(settings)
        for kind, percent in (("claude", 20), ("codex", 80)):
            data = ProviderSnapshot(kind, kind, "/" + kind)
            data.api = ApiUsage([LimitInfo("session", "session", percent, None)], None, NOW)
            state.accounts.append(data)
        self.assertEqual(state.icon_percent(), 50)
        self.assertIsNone(state.icon_kind())
        settings._values["iconMode"] = "highest"
        self.assertEqual(state.icon_percent(), 80)
        self.assertEqual(state.icon_kind(), "codex")
        settings._values["iconMode"] = "single"
        self.assertEqual(state.icon_percent(), 20)
        self.assertEqual(state.icon_kind(), "claude")
        settings._values["defaultAccountID"] = state.accounts[1].id
        self.assertEqual(state.icon_kind(), "codex")
        settings._values["colorMetric"] = "daily"
        self.assertIsNone(state.icon_percent())
        self.assertEqual(state.icon_kind(), "codex")
        settings._values["iconMode"] = "highest"
        self.assertIsNone(state.icon_kind())

    def test_provider_order_disable_and_failure_isolation(self):
        class Fake:
            name = "Test"
            def scan(self, *args):
                return ["ok"]
        class Broken(Fake):
            def scan(self, *args):
                raise OSError("fixture")
        settings = Settings().snapshot()
        settings._values.update(providerOrder=["codex", "claude"], enabledProviders=["claude", "codex"])
        results = collect({"claude": Fake(), "codex": Broken()}, settings)
        self.assertEqual(results[0].kind, "codex")
        self.assertEqual(results[1], "ok")
        settings._values["enabledProviders"] = ["claude"]
        self.assertEqual(collect({"claude": Fake(), "codex": Broken()}, settings), ["ok"])


if __name__ == "__main__":
    unittest.main()
