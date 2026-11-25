"""Opt-in adapter from read-only access-log findings to an injected admin sink.

This module has no transport implementation. Deployments must provide an
explicit receiver path and sender; successful finding keys are deduplicated
only for this worker instance (no alert state is written to any database).
"""

import logging
import math
import sqlite3
import threading
import time
from contextlib import closing
from datetime import date, timedelta
from pathlib import Path


logger = logging.getLogger("opensigan.admin_anomaly_alert")
_THRESHOLD_KEYS = {
    "window_hours", "max_requests_per_ip", "max_error_ratio",
    "max_distinct_schools", "min_requests", "max_status_errors",
}


def _validate_thresholds(thresholds):
    if not isinstance(thresholds, dict) or set(thresholds) != _THRESHOLD_KEYS:
        raise ValueError("all anomaly thresholds must be explicitly supplied")
    integer_limits = {
        "window_hours": (1, 720),
        "max_requests_per_ip": (1, 100000),
        "max_distinct_schools": (1, 100000),
        "min_requests": (0, 1000000),
        "max_status_errors": (1, 100000),
    }
    validated = dict(thresholds)
    for key, (minimum, maximum) in integer_limits.items():
        value = validated[key]
        if type(value) is not int or not minimum <= value <= maximum:
            raise ValueError("invalid anomaly threshold")
    ratio = validated["max_error_ratio"]
    if type(ratio) not in (int, float) or not math.isfinite(ratio) or not 0 < ratio <= 1:
        raise ValueError("invalid anomaly threshold")
    validated["max_error_ratio"] = float(ratio)
    return validated


def _review_read_only(store, thresholds):
    from backend.query_anomalies import detect

    today = date.fromisoformat(store._current_day())
    earliest_day = (today - timedelta(days=store.retention_days - 1)).isoformat()
    if store.path == ":memory:":
        db = store._connect()
    else:
        path = Path(store.path)
        if not path.is_file():
            raise OSError("access log database is unavailable")
        db = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=0.1)
        db.row_factory = sqlite3.Row
    with closing(db):
        return detect(db, **thresholds, earliest_day=earliest_day)


class AdminAnomalyAlertWorker:
    """Review configured findings and pass new ones to an injected sender.

    Disabled or incompletely configured workers do not inspect the store.
    Failed deliveries are left eligible for retry on the next run.
    """

    def __init__(self, store, *, enabled=False, thresholds=None, receiver_path="", sender=None, retry_seconds=60, clock=time.monotonic):
        self.store = store
        self.enabled = enabled is True
        self.thresholds = thresholds
        self.receiver_path = receiver_path.strip() if isinstance(receiver_path, str) else ""
        self.sender = sender
        self._sent = set()
        if not isinstance(retry_seconds, (int, float)) or isinstance(retry_seconds, bool) or not math.isfinite(retry_seconds) or retry_seconds <= 0:
            raise ValueError("retry_seconds must be positive and finite")
        self.retry_seconds = retry_seconds
        self.clock = clock
        self._retry_at = {}
        self._lock = threading.Lock()

    def run_once(self):
        if (not self.enabled or self.store is None or self.thresholds is None or
                not self.receiver_path or not callable(self.sender)):
            return 0

        thresholds = _validate_thresholds(self.thresholds)
        with self._lock:
            try:
                findings = _review_read_only(self.store, thresholds)
            except (OSError, sqlite3.Error):
                logger.warning("admin anomaly review unavailable")
                return 0

            keyed = [
                ((item.get("client_ip"), item.get("kind"), item.get("status_group")), item)
                for item in findings
            ]
            active = {key for key, _ in keyed}
            self._sent.intersection_update(active)
            self._retry_at = {key: deadline for key, deadline in self._retry_at.items() if key in active}
            delivered = 0
            for key, finding in keyed:
                if key in self._sent or self.clock() < self._retry_at.get(key, 0):
                    continue
                try:
                    sent = self.sender(self.receiver_path, dict(finding))
                except Exception:
                    logger.warning("admin anomaly notification failed")
                    self._retry_at[key] = self.clock() + self.retry_seconds
                    continue
                if sent is True:
                    self._sent.add(key)
                    self._retry_at.pop(key, None)
                    delivered += 1
                else:
                    logger.warning("admin anomaly notification failed")
                    self._retry_at[key] = self.clock() + self.retry_seconds
            return delivered
