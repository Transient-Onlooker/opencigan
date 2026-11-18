import json
import logging
import math
import threading
import time
from collections import OrderedDict
from datetime import datetime, timezone

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
        self.guard = threading.Lock()
        self.locks = tuple(threading.Lock() for _ in range(lock_stripes))

    def get(self, key, fetch, *, with_status=False):
        def output(value, status):
            return (value, status) if with_status else value

        resource = key[0] if isinstance(key, tuple) and key and key[0] in RESOURCE_TYPES else None

        now = time.monotonic()
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

        lock = self.locks[hash(key) % len(self.locks)]
        with lock:
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
                        self.refresh_observations[resource] = {"result": "failure", "observedAt": datetime.now(timezone.utc).isoformat()}
                logger.warning("cache refresh failed resource=%s fallback=%s error_type=%s",
                               resource or "other", "stale" if previous_value is not None else "none", type(exc).__name__)
                if previous_value is not None:
                    return output(self._stale(previous_value), "stale")
                if self.retry_delay > 0:
                    raise CacheBackoffError(self.retry_delay) from exc
                raise

            with self.guard:
                if resource:
                    self.refresh_observations[resource] = {"result": "success", "observedAt": datetime.now(timezone.utc).isoformat()}
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
