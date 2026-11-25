import sqlite3
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch
import os
import tempfile
from pathlib import Path

from backend.access_logs import AccessLogStore
from backend.admin_anomaly_alert_worker import AdminAnomalyAlertWorker, main, run_persistent_once


SEOUL = timezone(timedelta(hours=9))
THRESHOLDS = {
    "window_hours": 3,
    "max_requests_per_ip": 10,
    "max_error_ratio": 0.5,
    "max_distinct_schools": 5,
    "min_requests": 2,
    "max_status_errors": 1,
}


class AdminAnomalyAlertWorkerTests(unittest.TestCase):
    def test_persistent_worker_is_inert_without_explicit_enable(self):
        log_store, alert_store, sender = Mock(), Mock(), Mock()
        self.assertFalse(run_persistent_once(log_store, alert_store, {}, "", b"", sender=sender))
        log_store._connect.assert_not_called()
        alert_store.sync_findings.assert_not_called()
        sender.assert_not_called()
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(main())

    def test_main_incomplete_configuration_does_not_initialize_state(self):
        with patch.dict(os.environ, {"OPENCIGAN_ADMIN_ALERT_ENABLED": "1"}, clear=True), \
             patch("backend.admin_alert_store.AdminAlertStore") as state:
            with self.assertRaises(SystemExit):
                main()
            state.assert_not_called()

    def test_persistent_worker_restarts_without_duplicate_delivery(self):
        from backend.admin_alert_store import AdminAlertStore

        log_store = self.make_store()
        self.record_status_mix(log_store, datetime.now(SEOUL))
        sender = Mock(return_value={"delivered": True, "retryable": False})
        root = Path(os.environ["LOCALAPPDATA"]) / "Temp" if os.name == "nt" else None
        with tempfile.TemporaryDirectory(dir=root) as directory:
            path = Path(directory) / "alerts.sqlite"
            destination = "https://discord.com/api/webhooks/123/test_token"
            first = AdminAlertStore(path, b"i" * 32)
            self.assertTrue(run_persistent_once(log_store, first, THRESHOLDS, destination, b"s" * 32, enabled=True, sender=sender))
            second = AdminAlertStore(path, b"i" * 32)
            self.assertFalse(run_persistent_once(log_store, second, THRESHOLDS, destination, b"s" * 32, enabled=True, sender=sender))
            self.assertEqual(sender.call_count, 1)
            self.assertNotIn(b"203.0.113.1", path.read_bytes())

    def test_persistent_worker_retries_with_same_event_id_and_preserves_pending_on_read_failure(self):
        from backend.admin_alert_store import AdminAlertStore

        log_store = self.make_store()
        self.record_status_mix(log_store, datetime.now(SEOUL))
        sender = Mock(side_effect=[{"delivered": False, "retryable": True}, {"delivered": True}])
        root = Path(os.environ["LOCALAPPDATA"]) / "Temp" if os.name == "nt" else None
        with tempfile.TemporaryDirectory(dir=root) as directory:
            state = AdminAlertStore(Path(directory) / "alerts.sqlite", b"i" * 32)
            destination = "https://discord.com/api/webhooks/123/test_token"
            args = (log_store, state, THRESHOLDS, destination, b"s" * 32)
            self.assertTrue(run_persistent_once(*args, enabled=True, now=100, sender=sender))
            with patch("backend.admin_anomaly_alert_worker._review_read_only", side_effect=sqlite3.OperationalError):
                with self.assertRaises(sqlite3.OperationalError):
                    run_persistent_once(*args, enabled=True, now=160, sender=sender)
            self.assertEqual(sender.call_count, 1)
            self.assertTrue(run_persistent_once(*args, enabled=True, now=160, sender=sender))
            self.assertEqual(sender.call_args_list[0].args[3], sender.call_args_list[1].args[3])

    def make_store(self):
        store = AccessLogStore(":memory:")
        self.addCleanup(store.close)
        return store

    @staticmethod
    def record_status_mix(store, timestamp, client_ip="203.0.113.1"):
        for status in (404, 404, 200, 200):
            store.record({
                "client_ip": client_ip, "route": "/api/v1/timetable", "status": status,
                "duration_ms": 1.0, "origin_class": "external",
            }, received_at=timestamp)

    def worker(self, store, sender, **overrides):
        options = {"enabled": True, "thresholds": THRESHOLDS,
                   "receiver_path": "admin://alerts", "sender": sender}
        options.update(overrides)
        return AdminAnomalyAlertWorker(store, **options)

    def test_default_and_incomplete_configuration_do_not_review_or_send(self):
        for options in (
            {},
            {"enabled": True},
            {"enabled": True, "thresholds": THRESHOLDS},
            {"enabled": True, "receiver_path": "admin://alerts", "sender": Mock()},
            {"enabled": True, "thresholds": THRESHOLDS, "receiver_path": "admin://alerts"},
        ):
            with self.subTest(options=options):
                store = Mock()
                worker = AdminAnomalyAlertWorker(store, **options)
                self.assertEqual(worker.run_once(), 0)
                store._connect.assert_not_called()

    def test_all_thresholds_are_required_and_validated_before_opening_store(self):
        store = Mock()
        worker = self.worker(store, Mock(return_value=True), thresholds={
            key: value for key, value in THRESHOLDS.items() if key != "max_status_errors"
        })
        with self.assertRaises(ValueError):
            worker.run_once()
        store._connect.assert_not_called()

    def test_real_store_sliding_window_deduplicates_active_alert_and_realerts_after_clear(self):
        store = self.make_store()
        start = datetime.now(SEOUL).replace(microsecond=0)
        self.record_status_mix(store, start - timedelta(hours=2))
        purge = Mock(wraps=store._purge_if_due)
        store._purge_if_due = purge
        sent = []
        worker = self.worker(store, lambda receiver, finding: sent.append((receiver, finding)) or True)

        with patch("backend.query_anomalies._cutoff_iso", return_value=(start - timedelta(hours=3)).isoformat()):
            self.assertEqual(worker.run_once(), 1)
        initial_first_seen = sent[-1][1]["first_seen"]

        self.record_status_mix(store, start + timedelta(hours=1))
        purge_before_review = purge.call_count
        with patch("backend.query_anomalies._cutoff_iso", return_value=(start - timedelta(hours=1)).isoformat()):
            self.assertEqual(worker.run_once(), 0)
        with closing(store._connect()) as db:
            updated_first_seen = db.execute(
                "SELECT MIN(timestamp) FROM access_logs WHERE timestamp >= ?",
                ((start - timedelta(hours=1)).isoformat(),),
            ).fetchone()[0]
        self.assertNotEqual(initial_first_seen, updated_first_seen)
        self.assertEqual(len(sent), 1)
        self.assertEqual(purge.call_count, purge_before_review)

        purge_before_review = purge.call_count
        with patch("backend.query_anomalies._cutoff_iso", return_value=(start + timedelta(hours=3)).isoformat()):
            self.assertEqual(worker.run_once(), 0)
        self.assertEqual(purge.call_count, purge_before_review)
        self.record_status_mix(store, start + timedelta(hours=6))
        purge_before_review = purge.call_count
        with patch("backend.query_anomalies._cutoff_iso", return_value=(start + timedelta(hours=4)).isoformat()):
            self.assertEqual(worker.run_once(), 1)
        self.assertEqual(len(sent), 2)
        self.assertEqual(purge.call_count, purge_before_review)

    def test_failed_delivery_is_not_marked_and_is_retried(self):
        store = self.make_store()
        self.record_status_mix(store, datetime.now(SEOUL))
        sender = Mock(side_effect=[RuntimeError("mock failure"), True])
        clock = Mock(return_value=100.0)
        worker = self.worker(store, sender, clock=clock, retry_seconds=60)

        self.assertEqual(worker.run_once(), 0)
        self.assertEqual(worker.run_once(), 0)
        self.assertEqual(sender.call_count, 1)
        clock.return_value = 160.0
        self.assertEqual(worker.run_once(), 1)
        self.assertEqual(sender.call_count, 2)

    def test_read_failure_skips_delivery_and_later_run_can_succeed(self):
        store = self.make_store()
        self.record_status_mix(store, datetime.now(SEOUL))
        connect = store._connect
        with patch.object(store, "_connect", side_effect=[sqlite3.OperationalError("mock failure"), connect()]):
            sender = Mock(return_value=True)
            worker = self.worker(store, sender)
            self.assertEqual(worker.run_once(), 0)
            sender.assert_not_called()
            self.assertEqual(worker.run_once(), 1)
            sender.assert_called_once()

    def test_status_groups_are_distinct_and_concurrent_runs_do_not_double_send(self):
        store = self.make_store()
        timestamp = datetime.now(SEOUL)
        self.record_status_mix(store, timestamp)
        self.record_status_mix(store, timestamp, client_ip="203.0.113.2")
        send_lock = threading.Lock()
        sent = []

        def sender(receiver, finding):
            time.sleep(0.005)
            with send_lock:
                sent.append((receiver, finding["client_ip"], finding.get("status_group")))
            return True

        worker = self.worker(store, sender)
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: worker.run_once(), range(4)))

        self.assertEqual(sum(results), 2)
        self.assertCountEqual(sent, [
            ("admin://alerts", "203.0.113.1", "404"),
            ("admin://alerts", "203.0.113.2", "404"),
        ])


if __name__ == "__main__":
    unittest.main()
