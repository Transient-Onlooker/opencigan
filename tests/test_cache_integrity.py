import unittest
import threading
from concurrent.futures import ThreadPoolExecutor
from urllib.error import HTTPError, URLError
from unittest.mock import patch

from backend.cache import Cache, CacheBackoffError
from backend.comcigan_proxy import with_comcigan_budget


class CacheIntegrityTests(unittest.TestCase):
    def test_last_failure_kind_distinguishes_network_and_http_without_private_details(self):
        for error, kind in ((URLError('secret'), 'network'),
                            (HTTPError('https://private.invalid', 403, 'secret', {}, None), 'http'),
                            (URLError(TimeoutError('secret')), 'timeout'),
                            (TypeError('secret'), 'other')):
            with self.subTest(kind=kind):
                cache = Cache(retry_delay=0)
                with self.assertLogs('opensigan.cache', level='WARNING'):
                    with self.assertRaises(type(error)):
                        cache.get(('timetable', 'private-school', 'week'), lambda: (_ for _ in ()).throw(error))
                observation = cache.observations()['timetable']
                self.assertEqual(observation['lastFailureKind'], kind)
                self.assertNotIn('secret', str(observation))
                self.assertNotIn('private', str(observation))

    def test_non_comcigan_wait_does_not_use_comcigan_budget(self):
        cache = Cache(lock_stripes=1)
        key = ('meals', 'school')
        entered, release = threading.Event(), threading.Event()
        def slow():
            entered.set()
            if not release.wait(2):
                raise AssertionError('fixture was not released')
            return {'meals': []}
        @with_comcigan_budget
        def follower():
            return cache.get(key, lambda: self.fail('duplicate fetch'))
        with patch('backend.comcigan_proxy.UPSTREAM_BUDGET_SECONDS', 0.01):
            with ThreadPoolExecutor(max_workers=2) as pool:
                first = pool.submit(cache.get, key, slow)
                self.assertTrue(entered.wait(1))
                second = pool.submit(follower)
                try:
                    threading.Event().wait(0.03)
                    self.assertFalse(second.done())
                finally:
                    release.set()
                self.assertEqual(first.result(timeout=1), {'meals': []})
                self.assertEqual(second.result(timeout=1), {'meals': []})

    def test_waiter_releases_lock_if_deadline_expires_on_acquisition(self):
        cache = Cache(lock_stripes=1)
        key = ('timetable', 'school', 'week')
        class BoundaryLock:
            released = False
            def acquire(self, blocking=True, timeout=-1):
                return blocking
            def release(self):
                self.released = True
        lock = BoundaryLock()
        cache._flights[0][key] = [lock, 0]
        with patch('backend.cache.remaining_comcigan_budget', side_effect=[1.0, 0.0]):
            with cache._singleflight(key) as acquired:
                self.assertFalse(acquired)
        self.assertTrue(lock.released)
        self.assertFalse(cache._flights[0])

    def test_budgeted_waiter_times_out_without_poisoning_inflight_result(self):
        cache = Cache(lock_stripes=1)
        key = ('timetable', 'school', 'week')
        entered, release = threading.Event(), threading.Event()

        def slow():
            entered.set()
            if not release.wait(2):
                raise AssertionError('fixture was not released')
            return {'records': []}

        @with_comcigan_budget
        def follower():
            return cache.get(key, lambda: self.fail('duplicate fetch'))

        with patch('backend.comcigan_proxy.UPSTREAM_BUDGET_SECONDS', 0.05):
            with ThreadPoolExecutor(max_workers=2) as pool:
                leader = pool.submit(cache.get, key, slow)
                self.assertTrue(entered.wait(1))
                try:
                    waiter = pool.submit(follower)
                    with self.assertRaises(TimeoutError):
                        waiter.result(timeout=1)
                    self.assertNotIn(key, cache.entries)
                finally:
                    release.set()
                self.assertEqual(leader.result(timeout=1), {'records': []})
        self.assertEqual(cache.get(key, lambda: self.fail('cache hit')), {'records': []})
        self.assertFalse(cache._flights[0])

    def test_singleflight_wait_observation_records_only_contention_without_key(self):
        cache = Cache(lock_stripes=1)
        key = ('timetable', 'private-school')
        entered, release, waiting = threading.Event(), threading.Event(), threading.Event()
        class TrackingLock:
            def __init__(self, inner):
                self.inner = inner
            def acquire(self, blocking=True):
                if blocking:
                    waiting.set()
                return self.inner.acquire(blocking)
            def release(self):
                self.inner.release()
        def slow():
            entered.set()
            if not release.wait(3):
                raise TimeoutError('fixture was not released')
            return {'records': []}
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(cache.get, key, slow)
            self.assertTrue(entered.wait(2))
            with cache.locks[0]:
                cache._flights[0][key][0] = TrackingLock(cache._flights[0][key][0])
            second = pool.submit(cache.get, key, lambda: self.fail('duplicate fetch'))
            try:
                self.assertTrue(waiting.wait(2), 'second request did not wait for the flight')
            finally:
                release.set()
            self.assertEqual(first.result(timeout=2), {'records': []})
            self.assertEqual(second.result(timeout=2), {'records': []})
        waits = cache.waits()
        self.assertGreaterEqual(waits['timetable']['waitMs'], 0)
        self.assertIn('observedAt', waits['timetable'])
        self.assertNotIn('private-school', str(waits))
        self.assertEqual(cache.get(key, lambda: self.fail('cache hit')), {'records': []})
        self.assertEqual(cache.waits(), waits)

    def test_waiter_shares_backoff_after_inflight_timeout(self):
        cache = Cache(retry_delay=30, lock_stripes=1)
        key = ('timetable', 'private-school')
        entered, release, waiting = threading.Event(), threading.Event(), threading.Event()
        calls = []

        class TrackingLock:
            def __init__(self, inner):
                self.inner = inner

            def acquire(self, blocking=True):
                if blocking:
                    waiting.set()
                return self.inner.acquire(blocking)

            def release(self):
                self.inner.release()

        def timeout():
            calls.append(1)
            entered.set()
            if not release.wait(3):
                raise AssertionError('fixture was not released')
            raise TimeoutError('private upstream detail')

        with self.assertLogs('opensigan.cache', level='WARNING') as logs:
            with ThreadPoolExecutor(max_workers=2) as pool:
                first = pool.submit(cache.get, key, timeout)
                self.assertTrue(entered.wait(2))
                with cache.locks[0]:
                    cache._flights[0][key][0] = TrackingLock(cache._flights[0][key][0])
                second = pool.submit(cache.get, key, timeout)
                try:
                    self.assertTrue(waiting.wait(2))
                finally:
                    release.set()
                with self.assertRaises(CacheBackoffError) as leader:
                    first.result(timeout=2)
                with self.assertRaises(CacheBackoffError) as follower:
                    second.result(timeout=2)
        self.assertIsInstance(leader.exception.__cause__, TimeoutError)
        self.assertGreater(follower.exception.retry_after, 0)
        self.assertEqual(calls, [1])
        self.assertGreaterEqual(cache.waits()['timetable']['waitMs'], 0)
        self.assertNotIn('private-school', str(cache.waits()))
        self.assertNotIn('private upstream detail', str(logs.output))
        self.assertTrue(all(not flights for flights in cache._flights))

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
        self.assertEqual(failure["school_search"]["lastFailureKind"], "provider_response")
        self.assertNotIn("private", str(failure))
        failure["school_search"]["result"] = "tampered"
        self.assertEqual(cache.observations()["school_search"]["result"], "failure")
        cache.get(key, lambda: {"schools": []})
        self.assertEqual(cache.observations()["school_search"]["result"], "success")
        self.assertEqual(cache.observations()["school_search"]["lastFailureAt"], failure["school_search"]["lastFailureAt"])
        self.assertEqual(cache.observations()["school_search"]["lastFailureKind"], "provider_response")

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

    def test_wrapped_http_error_logs_cause_without_private_data(self):
        cache = Cache(retry_delay=0)
        error = HTTPError("https://private.test/?token=secret", 429, "private response", {}, None)
        self.addCleanup(error.close)

        def fail():
            try:
                raise error
            except HTTPError as exc:
                raise RuntimeError("private wrapper") from exc

        with self.assertLogs("opensigan.cache", level="WARNING") as logs:
            with self.assertRaises(RuntimeError):
                cache.get(("school_search", "private-school"), fail)
        self.assertIn("error_type=RuntimeError upstream_http_status=429 cause_type=HTTPError", logs.output[0])
        for secret in ("private.test", "token", "secret", "private response", "private wrapper", "private-school"):
            self.assertNotIn(secret, logs.output[0])

    def test_wrapped_connection_error_is_classified_without_message(self):
        cache = Cache(retry_delay=0)

        def fail():
            try:
                raise ConnectionResetError("private connection")
            except ConnectionResetError as exc:
                raise RuntimeError("private wrapper") from exc

        with self.assertLogs("opensigan.cache", level="WARNING") as logs:
            with self.assertRaises(RuntimeError):
                cache.get(("school_search", "private-school"), fail)
        self.assertIn("cause_type=OSError", logs.output[0])
        self.assertNotIn("private", logs.output[0])

    def test_suppressed_error_is_not_inferred_from_context(self):
        cache = Cache(retry_delay=0)

        def fail():
            try:
                raise HTTPError("https://private.test", 403, "private", {}, None)
            except HTTPError:
                raise RuntimeError("private wrapper") from None

        with self.assertLogs("opensigan.cache", level="WARNING") as logs:
            with self.assertRaises(RuntimeError):
                cache.get(("school_search", "private-school"), fail)
        self.assertIn("upstream_http_status=None cause_type=RuntimeError", logs.output[0])
        self.assertNotIn("private", logs.output[0])

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
