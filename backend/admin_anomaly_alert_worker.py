"""Opt-in processing of access-log findings for administrator alerts.

The standalone worker uses a separate persistent outbox and requires explicit
configuration. The injected adapter keeps its deduplication in memory.
"""

import logging
import math
import os
import signal
import sqlite3
import threading
import time
from contextlib import closing
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace


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


def run_persistent_once(log_store, alert_store, thresholds, destination, secret, *, enabled=False, now=None, sender=None):
    """Review once and process a bounded batch using a separate persistent outbox."""
    if not enabled:
        return False
    from backend.admin_alert_delivery import send_admin_alert

    if not log_store or not alert_store or not destination or not isinstance(secret, bytes) or len(secret) < 32:
        raise ValueError("complete administrator alert configuration is required")
    thresholds = _validate_thresholds(thresholds)
    findings = _review_read_only(log_store, thresholds)
    alert_store.sync_findings(findings, now=now)
    alert_store.prune(now=now)
    processed = False
    for _ in range(20):
        delivery = alert_store.claim(now=now)
        if delivery is None:
            break
        payload = delivery["payload"]
        try:
            options = {"send": sender} if sender is not None else {}
            result = send_admin_alert(destination, secret, delivery["event_id"], payload["kind"], payload.get("status_group"), **options)
        except (ValueError, OSError):
            result = {"delivered": False, "retryable": False}
        alert_store.finish(delivery["id"], delivery["lease_token"], delivered=result["delivered"],
                           retryable=result.get("retryable", True), now=now)
        processed = True
    return processed


def main():
    if os.environ.get("OPENCIGAN_ADMIN_ALERT_ENABLED") != "1":
        return
    from datetime import datetime, timedelta, timezone
    from backend.admin_alert_store import AdminAlertStore
    from backend.webhook_delivery import validate_destination

    try:
        log_path = Path(os.environ["OPENCIGAN_ACCESS_LOG_DB"]).resolve(strict=True)
        state_path = Path(os.environ["OPENCIGAN_ADMIN_ALERT_DB"]).absolute()
        if state_path.resolve() == log_path or (state_path.exists() and os.path.samefile(state_path, log_path)):
            raise ValueError("alert state must use a separate database")
        destination = os.environ["OPENCIGAN_ADMIN_ALERT_DESTINATION"]
        validate_destination(destination)
        secret = os.environ["OPENCIGAN_ADMIN_ALERT_SIGNING_KEY"].encode("utf-8")
        hmac_key = os.environ["OPENCIGAN_ADMIN_ALERT_ID_KEY"].encode("utf-8")
        if len(secret) < 32 or len(hmac_key) < 32:
            raise ValueError("administrator alert keys must contain at least 32 bytes")
        thresholds = _validate_thresholds({
            "window_hours": int(os.environ["OPENCIGAN_ADMIN_ALERT_WINDOW_HOURS"]),
            "max_requests_per_ip": int(os.environ["OPENCIGAN_ADMIN_ALERT_MAX_REQUESTS"]),
            "max_error_ratio": float(os.environ["OPENCIGAN_ADMIN_ALERT_MAX_ERROR_RATIO"]),
            "max_distinct_schools": int(os.environ["OPENCIGAN_ADMIN_ALERT_MAX_SCHOOLS"]),
            "min_requests": int(os.environ["OPENCIGAN_ADMIN_ALERT_MIN_REQUESTS"]),
            "max_status_errors": int(os.environ["OPENCIGAN_ADMIN_ALERT_MAX_STATUS_ERRORS"]),
        })
        interval = int(os.environ["OPENCIGAN_ADMIN_ALERT_INTERVAL_SECONDS"])
        retention = int(os.environ.get("OPENCIGAN_ACCESS_LOG_RETENTION_DAYS", "7"))
        if not 10 <= interval <= 3600 or not 1 <= retention <= 90 or not log_path.is_file():
            raise ValueError("invalid administrator alert configuration")
    except (KeyError, ValueError, OSError):
        raise SystemExit("Administrator alerts require a valid explicit configuration") from None

    log_store = SimpleNamespace(path=str(log_path), retention_days=retention,
        _current_day=lambda: datetime.now(timezone(timedelta(hours=9))).date().isoformat())
    alert_store = AdminAlertStore(state_path, hmac_key)
    stop = threading.Event()
    for name in ("SIGINT", "SIGTERM"):
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), lambda *_: stop.set())
    while not stop.is_set():
        try:
            run_persistent_once(log_store, alert_store, thresholds, destination, secret, enabled=True)
        except (OSError, sqlite3.Error, ValueError):
            logger.warning("admin anomaly alert processing unavailable")
        stop.wait(interval)


if __name__ == "__main__":
    main()
