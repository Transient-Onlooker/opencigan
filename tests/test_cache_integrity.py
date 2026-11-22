import unittest
import threading
from concurrent.futures import ThreadPoolExecutor
from urllib.error import HTTPError
from unittest.mock import patch

from backend.cache import Cache


class CacheIntegrityTests(unittest.TestCase):
    def test_distinct_keys_do_not_block_when_lock_stripes_collide(self):
        cache = Cache(lock_stripes=1)
        started, release, fast_done = threading.Event(), threading.Event(), threading.Event()

        def slow_fetch():
            started.set()
            if not release.wait(3):
                raise TimeoutError("fixture was not released")
            return {"value": "slow"}

        def fast_fetch():
            fast_done.set()
            return {"value": "fast"}

        with ThreadPoolExecutor(max_workers=2) as pool:
            slow = pool.submit(cache.get, ("timetable", "slow"), slow_fetch)
            self.assertTrue(started.wait(2))
            fast = pool.submit(cache.get, ("timetable", "fast"), fast_fetch)
            try:
                self.assertTrue(fast_done.wait(1), "a different key should not wait for the slow fetch")
                self.assertEqual(fast.result(timeout=2), {"value": "fast"})
            finally:
                release.set()
            self.assertEqual(slow.result(timeout=2), {"value": "slow"})
        self.assertTrue(all(not flights for flights in cache._flights))

    def test_singleflight_entries_are_removed_after_errors(self):
        cache = Cache(retry_delay=0, lock_stripes=1)
        with self.assertLogs("opensigan.cache", level="WARNING"):
            with self.assertRaises(RuntimeError):
                cache.get(("timetable", "failure"), lambda: (_ for _ in ()).throw(RuntimeError("fixture")))
        self.assertTrue(all(not flights for flights in cache._flights))

    def test_refresh_duration_records_completed_attempts_not_hits_or_backoff(self):
        cache = Cache(ttl=60, retry_delay=60)
        clock = [100.0]
        key = ("timetable", "private-school")

        def success():
            clock[0] += 1.25
            return {"records": []}

        def fail():
            clock[0] += 2.5
            raise TimeoutError("private details")

        with patch("backend.cache.time.monotonic", side_effect=lambda: clock[0]):
            cache.get(key, success)
            self.assertEqual(cache.observations()["timetable"]["durationMs"], 1250)
            cache.get(key, lambda: self.fail("cache hit must not fetch"))
            self.assertEqual(cache.observations()["timetable"]["durationMs"], 1250)
            cache.ttl = 0
            with self.assertLogs("opensigan.cache", level="WARNING"):
                self.assertTrue(cache.get(key, fail)["stale"])
            self.assertEqual(cache.observations()["timetable"]["durationMs"], 2500)
            self.assertTrue(cache.get(key, lambda: self.fail("backoff must not fetch"))["stale"])
            self.assertEqual(cache.observations()["timetable"]["durationMs"], 2500)
        self.assertNotIn("private", str(cache.observations()))

    def test_refresh_observations_are_private_and_change_only_on_fetch(self):
        cache = Cache(ttl=60, retry_delay=60)
        key = ("school_search", "private-school")
        self.assertEqual(cache.observations(), {})
        cache.get(key, lambda: {"schools": []})
        first = cache.observations()
        self.assertEqual(first["school_search"]["result"], "success")
        self.assertEqual(first["school_search"]["lastSuccessAt"], first["school_search"]["observedAt"])
        self.assertNotIn("private-school", str(first))
        cache.get(key, lambda: self.fail("cache hit must not fetch"))
        self.assertEqual(cache.observations(), first)
        cache.ttl = 0
        cache.retry_delay = 0
        with self.assertLogs("opensigan.cache", level="WARNING"):
            cache.get(key, lambda: (_ for _ in ()).throw(RuntimeError("private error")))
        failure = cache.observations()
        self.assertEqual(failure["school_search"]["result"], "failure")
        self.assertEqual(failure["school_search"]["lastSuccessAt"], first["school_search"]["lastSuccessAt"])
        self.assertEqual(failure["school_search"]["lastFailureAt"], failure["school_search"]["observedAt"])
        self.assertNotIn("private", str(failure))
        failure["school_search"]["result"] = "tampered"
        self.assertEqual(cache.observations()["school_search"]["result"], "failure")
        cache.get(key, lambda: {"schools": []})
        self.assertEqual(cache.observations()["school_search"]["result"], "success")
        self.assertEqual(cache.observations()["school_search"]["lastFailureAt"], failure["school_search"]["lastFailureAt"])

    def test_failed_refresh_logs_resource_and_fallback_without_request_data(self):
        cache = Cache(ttl=0, retry_delay=60)
        key = ("timetable", "private-school", "2026-11-09")
        cache.get(key, lambda: {"value": "old"})

        def fail():
            raise OSError("secret upstream response")

        with self.assertLogs("opensigan.cache", level="WARNING") as logs:
            self.assertTrue(cache.get(key, fail)["stale"])
            self.assertTrue(cache.get(key, fail)["stale"])
        self.assertEqual(len(logs.output), 1)
        self.assertIn("resource=timetable fallback=stale error_type=OSError", logs.output[0])
        self.assertNotIn("private-school", logs.output[0])
        self.assertNotIn("secret upstream response", logs.output[0])

    def test_failed_uncached_fetch_logs_no_fallback(self):
        cache = Cache()

        def fail():
            raise RuntimeError("secret query")

        with self.assertLogs("opensigan.cache", level="WARNING") as logs:
            with self.assertRaises(RuntimeError):
                cache.get(("school_search", "private query"), fail)
        self.assertIn("resource=school_search fallback=none error_type=RuntimeError", logs.output[0])
        self.assertNotIn("private query", logs.output[0])
        self.assertNotIn("secret query", logs.output[0])

    def test_http_error_logs_status_without_url_or_message(self):
        cache = Cache(ttl=0, retry_delay=60)
        key = ("school_search", "private-school")
        cache.get(key, lambda: {"schools": []})

        error = HTTPError("https://example.test/?token=secret", 503, "private response", {}, None)
        self.addCleanup(error.close)

        def fail():
            raise error

        with self.assertLogs("opensigan.cache", level="WARNING") as logs:
            self.assertTrue(cache.get(key, fail)["stale"])
        self.assertIn("error_type=HTTPError upstream_http_status=503", logs.output[0])
        for secret in ("example.test", "token", "secret", "private response", "private-school"):
            self.assertNotIn(secret, logs.output[0])

    def test_eviction_during_failed_refresh_returns_inflight_stale_value(self):
        cache = Cache(ttl=0, max_entries=1, lock_stripes=2)
        cache.get(0, lambda: {"value": "old", "stale": False})
        started = threading.Event()
        release = threading.Event()

        def fail_after_eviction():
            started.set()
            if not release.wait(2):
                raise TimeoutError("refresh was not released")
            raise RuntimeError("upstream unavailable")

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(cache.get, 0, fail_after_eviction)
            try:
                self.assertTrue(started.wait(2))
                cache.get(1, lambda: {"value": "other"})
                self.assertNotIn(0, cache.entries)
            finally:
                release.set()
            self.assertEqual(future.result(timeout=2), {"value": "old", "stale": True})

        def fail_if_called():
            self.fail("backoff should serve the saved data without another request")

        self.assertEqual(cache.get(0, fail_if_called), {"value": "old", "stale": True})

    def test_oversized_refresh_preserves_last_good_value(self):
        cache = Cache(ttl=0, retry_delay=60, max_bytes=80)
        key = ("timetable", "private-school")
        cache.get(key, lambda: {"value": "old", "stale": False})
        result = cache.get(key, lambda: {"value": "x" * 100})
        self.assertEqual(result, {"value": "old", "stale": True})
        self.assertEqual(cache.observations()["timetable"]["result"], "not_cached")
        self.assertIn("lastSuccessAt", cache.observations()["timetable"])
        self.assertNotIn("lastFailureAt", cache.observations()["timetable"])

        def fail_if_called():
            self.fail("backoff should prevent another request")

        self.assertEqual(cache.get(key, fail_if_called), result)
        self.assertEqual(cache.observations()["timetable"]["result"], "not_cached")

    def test_oversized_initial_value_is_returned_without_caching(self):
        cache = Cache(max_bytes=10)
        value = {"value": "x" * 100}
        self.assertEqual(cache.get(("meals", "private-school"), lambda: value), value)
        self.assertEqual(len(cache.entries), 0)
        self.assertEqual(cache.observations()["meals"]["result"], "not_cached")


if __name__ == "__main__":
    unittest.main()
