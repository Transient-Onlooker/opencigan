import json
import logging
import math
import threading
import time
from collections import OrderedDict
from contextlib import contextmanager
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError

from backend.comcigan_proxy import remaining_comcigan_budget

logger = logging.getLogger("opensigan.cache")
RESOURCE_TYPES = frozenset(("timetable", "school_search", "neis_school_search", "meals"))


class CacheBackoffError(RuntimeError):
    def __init__(self, seconds):
        super().__init__("cached fetch failure is in backoff")
        self.retry_after = max(1, math.ceil(seconds))


class Cache:
    """Bounded, process-local cache with single-flight refreshes."""

    def __init__(self, ttl=1800, retry_delay=60, max_entries=256,
                 max_bytes=16 * 1024 * 1024, lock_stripes=64):
        if ttl < 0 or retry_delay < 0 or max_entries < 1 or max_bytes < 1 or lock_stripes < 1:
            raise ValueError("cache limits must be non-negative and capacities positive")
        self.ttl = ttl
        self.retry_delay = retry_delay
        self.max_entries = max_entries
        self.max_bytes = max_bytes
        self.bytes_used = 0
        self.entries = OrderedDict()
        self.refresh_observations = {}
        self.wait_observations = {}
        self.guard = threading.Lock()
        self.locks = tuple(threading.Lock() for _ in range(lock_stripes))
        self._flights = tuple({} for _ in range(lock_stripes))

    @contextmanager
    def _singleflight(self, key, *, wait=True):
        stripe = hash(key) % len(self.locks)
        with self.locks[stripe]:
            flight = self._flights[stripe].get(key)
            if flight is None:
                flight = [threading.Lock(), 0]
                self._flights[stripe][key] = flight
            flight[1] += 1
        try:
            acquired = flight[0].acquire(blocking=False)
            if not acquired and not wait:
                yield False
                return
            if not acquired:
                started_at = time.monotonic()
                resource = key[0] if isinstance(key, tuple) and key else None
                remaining = remaining_comcigan_budget() if resource in ('timetable', 'school_search') else None
                if remaining is None:
                    flight[0].acquire()
                else:
                    if remaining <= 0 or not flight[0].acquire(timeout=remaining):
                        yield False
                        return
            try:
                if not acquired:
                    if remaining is not None and remaining_comcigan_budget() <= 0:
                        yield False
                        return
                    resource = key[0] if isinstance(key, tuple) and key and key[0] in RESOURCE_TYPES else None
                    if resource:
                        elapsed = max(0, round((time.monotonic() - started_at) * 1000))
                        with self.guard:
                            self.wait_observations[resource] = {"waitMs": elapsed, "observedAt": datetime.now(timezone.utc).isoformat()}
                yield True
            finally:
                flight[0].release()
        finally:
            with self.locks[stripe]:
                flight[1] -= 1
                if flight[1] == 0:
                    del self._flights[stripe][key]

    def get(self, key, fetch, *, with_status=False):
        def output(value, status):
            return (value, status) if with_status else value

        resource = key[0] if isinstance(key, tuple) and key and key[0] in RESOURCE_TYPES else None

        now = time.monotonic()
        stale_while_refreshing = None
        with self.guard:
            entry = self.entries.get(key)
            if entry is not None:
                value, fetched_at, retry_after = entry
                if value is not None and now - fetched_at < self.ttl:
                    self.entries.move_to_end(key)
                    return output(json.loads(value), "hit")
                if retry_after > now:
                    if value is not None:
                        return output(self._stale(value), "stale")
                    raise CacheBackoffError(retry_after - now)
                if resource == "timetable" and value is not None:
                    stale_while_refreshing = value

        with self._singleflight(key, wait=stale_while_refreshing is None) as acquired:
            if not acquired:
                if stale_while_refreshing is not None:
                    return output(self._stale(stale_while_refreshing), "stale")
                with self.guard:
                    entry = self.entries.get(key)
                    if entry is not None and entry[0] is not None:
                        value, fetched_at, _ = entry
                        if time.monotonic() - fetched_at < self.ttl:
                            return output(json.loads(value), "hit")
                        return output(self._stale(value), "stale")
                raise TimeoutError("Comcigan request budget exhausted while waiting for cache")
            now = time.monotonic()
            previous_value = None
            previous_fetched_at = 0
            with self.guard:
                entry = self.entries.get(key)
                if entry is not None:
                    self.entries.move_to_end(key)
                    value, fetched_at, retry_after = entry
                    previous_value = value
                    previous_fetched_at = fetched_at
                    if value is not None and now - fetched_at < self.ttl:
                        return output(json.loads(value), "hit")
                    if retry_after > now:
                        if value is not None:
                            return output(self._stale(value), "stale")
                        raise CacheBackoffError(retry_after - now)

            started_at = time.monotonic()
            try:
                value = fetch()
                try:
                    cached = json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")
                except (TypeError, ValueError) as exc:
                    raise RuntimeError("fetch returned a non-JSON value") from exc
            except ValueError:
                raise
            except Exception as exc:
                now = time.monotonic()
                with self.guard:
                    self._store(key, previous_value, previous_fetched_at, now + self.retry_delay)
                    if resource:
                        observed_at = datetime.now(timezone.utc).isoformat()
                        self.refresh_observations[resource] = {**self.refresh_observations.get(resource, {}),
                                                               "result": "failure", "observedAt": observed_at,
                                                               "durationMs": max(0, round((now - started_at) * 1000)),
                                                               "lastFailureAt": observed_at}
                cause = exc
                for _ in range(8):
                    if cause.__cause__ is None:
                        break
                    cause = cause.__cause__
                status = cause.code if isinstance(cause, HTTPError) and type(cause.code) is int and 100 <= cause.code <= 599 else None
                cause_type = next((cls.__name__ for cls in (HTTPError, URLError, TimeoutError, OSError, ValueError, RuntimeError)
                                   if isinstance(cause, cls)), "other")
                failure_kind = ("timeout" if isinstance(cause, TimeoutError) or
                                isinstance(getattr(cause, "reason", None), TimeoutError) else
                                "http" if isinstance(cause, HTTPError) else
                                "network" if isinstance(cause, (URLError, OSError)) else
                                "provider_response" if isinstance(cause, (ValueError, RuntimeError)) else "other")
                logger.warning("cache refresh failed resource=%s fallback=%s error_type=%s upstream_http_status=%s cause_type=%s failure_kind=%s",
                               resource or "other", "stale" if previous_value is not None else "none", type(exc).__name__, status, cause_type, failure_kind)
                if previous_value is not None:
                    return output(self._stale(previous_value), "stale")
                if self.retry_delay > 0:
                    raise CacheBackoffError(self.retry_delay) from exc
                raise

            duration_ms = max(0, round((time.monotonic() - started_at) * 1000))
            with self.guard:
                if resource:
                    observed_at = datetime.now(timezone.utc).isoformat()
                    result = "success" if len(cached) <= self.max_bytes else "not_cached"
                    self.refresh_observations[resource] = {**self.refresh_observations.get(resource, {}),
                                                           "result": result, "observedAt": observed_at, "durationMs": duration_ms,
                                                           **({"lastSuccessAt": observed_at} if result == "success" else {})}
                if len(cached) <= self.max_bytes:
                    self._store(key, cached, time.monotonic(), 0)
                else:
                    old = self.entries.get(key)
                    if old and old[0] is not None:
                        self._store(key, old[0], old[1], time.monotonic() + self.retry_delay)
                        return output(self._stale(old[0]), "stale")
            return output(json.loads(cached), "miss")

    def observations(self):
        with self.guard:
            return {resource: value.copy() for resource, value in self.refresh_observations.items()}

    def waits(self):
        with self.guard:
            return {resource: value.copy() for resource, value in self.wait_observations.items()}

    @staticmethod
    def _stale(value):
        result = json.loads(value)
        if isinstance(result, dict):
            result["stale"] = True
        return result

    def _store(self, key, value, fetched_at, retry_after):
        old = self.entries.get(key)
        if old and old[0] is not None:
            self.bytes_used -= len(old[0])
        self.entries[key] = (value, fetched_at, retry_after)
        self.bytes_used += len(value) if value is not None else 0
        self.entries.move_to_end(key)
        while len(self.entries) > self.max_entries or self.bytes_used > self.max_bytes:
            _, removed = self.entries.popitem(last=False)
            self.bytes_used -= len(removed[0]) if removed[0] is not None else 0
