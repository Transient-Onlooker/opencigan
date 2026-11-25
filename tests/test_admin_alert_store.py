import sqlite3
import tempfile
import unittest
import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path

from backend.admin_alert_store import AdminAlertStore
from backend.admin_anomaly_alert_worker import run_persistent_once


class AdminAlertStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "admin-alerts.sqlite"
        self.key = b"k" * 32
        self.finding = {
            "client_ip": "203.0.113.7", "kind": "status_errors", "status_group": "404",
            "observed": 3, "threshold": 2, "requests": 8,
            "detail": "excluded detail", "school_id": "excluded school",
        }
        self.store = AdminAlertStore(self.path, self.key)

    def test_requires_separate_persistent_path_and_strong_key(self):
        with self.assertRaises(ValueError):
            AdminAlertStore(":memory:", self.key)
        with self.assertRaises(ValueError):
            AdminAlertStore(self.path, b"short")
        self.assertTrue(self.path.exists())

    def test_existing_unrelated_database_is_rejected_without_schema_changes(self):
        other = Path(self.temp.name) / "application.sqlite"
        with closing(sqlite3.connect(other)) as db:
            db.execute("CREATE TABLE existing_data (value TEXT)")
            db.execute("INSERT INTO existing_data VALUES ('preserve me')")
            db.commit()
        if os.name != "nt":
            other.chmod(0o600)
        with self.assertRaises(ValueError):
            AdminAlertStore(other, self.key)
        with closing(sqlite3.connect(other)) as db:
            self.assertEqual(db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall(),
                             [("existing_data",)])
            self.assertEqual(db.execute("SELECT value FROM existing_data").fetchone()[0], "preserve me")

    def test_existing_unidentified_empty_database_is_rejected(self):
        empty = Path(self.temp.name) / "empty.sqlite"
        sqlite3.connect(empty).close()
        if os.name != "nt":
            empty.chmod(0o600)
        with self.assertRaises(ValueError):
            AdminAlertStore(empty, self.key)

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks are unavailable")
    def test_symlink_path_is_rejected(self):
        target = Path(self.temp.name) / "target.sqlite"
        link = Path(self.temp.name) / "link.sqlite"
        target.write_bytes(b"preserve")
        try:
            link.symlink_to(target)
        except OSError:
            self.skipTest("symlink creation is not permitted")
        with self.assertRaises(ValueError):
            AdminAlertStore(link, self.key)
        self.assertEqual(target.read_bytes(), b"preserve")

    @unittest.skipIf(os.name == "nt", "POSIX permission bits are not available")
    def test_existing_database_with_broad_permissions_is_rejected(self):
        broad = Path(self.temp.name) / "broad.sqlite"
        broad.write_bytes(b"")
        broad.chmod(0o644)
        with self.assertRaises(PermissionError):
            AdminAlertStore(broad, self.key)

    def test_identity_is_hmac_only_and_payload_is_allowlisted(self):
        self.assertEqual(self.store.sync_findings([self.finding], now=100), 1)
        with closing(sqlite3.connect(self.path)) as db:
            alert_columns = {row[1] for row in db.execute("PRAGMA table_info(admin_alerts)")}
            self.assertNotIn("client_ip", alert_columns)
            alert = db.execute("SELECT fingerprint FROM admin_alerts").fetchone()[0]
            payload = db.execute("SELECT payload_json FROM admin_alert_deliveries").fetchone()[0]
        self.assertNotIn(self.finding["client_ip"], alert)
        self.assertNotIn(self.finding["client_ip"], payload)
        self.assertEqual(payload, '{"kind":"status_errors","status_group":"404"}')

    def test_repeated_sync_across_restart_creates_one_pending_delivery(self):
        self.assertEqual(self.store.sync_findings([self.finding], now=100), 1)
        restarted = AdminAlertStore(self.path, self.key)
        self.assertEqual(restarted.sync_findings([self.finding], now=110), 0)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM admin_alert_deliveries").fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT last_seen FROM admin_alerts").fetchone()[0], 110)

    def test_concurrent_syncs_reserve_one_episode(self):
        stores = [AdminAlertStore(self.path, self.key) for _ in range(8)]
        with ThreadPoolExecutor(max_workers=8) as pool:
            inserted = list(pool.map(lambda store: store.sync_findings([self.finding], now=100), stores))
        self.assertEqual(sum(inserted), 1)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM admin_alert_deliveries").fetchone()[0], 1)

    def test_concurrent_claims_lease_a_delivery_to_only_one_worker(self):
        self.store.sync_findings([self.finding], now=100)
        stores = [AdminAlertStore(self.path, self.key) for _ in range(8)]
        with ThreadPoolExecutor(max_workers=8) as pool:
            claimed = list(pool.map(lambda store: store.claim(now=100), stores))
        available = [item for item in claimed if item is not None]
        self.assertEqual(len(available), 1)

    def test_database_page_limit_is_applied_and_oversize_state_is_rejected(self):
        with closing(self.store._connect()) as db:
            page_size = db.execute("PRAGMA page_size").fetchone()[0]
            page_limit = db.execute("PRAGMA max_page_count").fetchone()[0]
            page_count = db.execute("PRAGMA page_count").fetchone()[0]
        self.assertEqual(page_limit * page_size, 32 * 1024 * 1024)
        self.assertLessEqual(page_count * page_size, 32 * 1024 * 1024)

        from unittest.mock import patch

        with patch("backend.admin_alert_store._MAX_DB_BYTES", page_size):
            with self.assertRaises(ValueError):
                self.store.sync_findings([self.finding], now=100)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM admin_alerts").fetchone()[0], 0)

    @unittest.skipIf(os.name == "nt", "POSIX permission bits are not available")
    def test_insecure_sqlite_sidecar_is_rejected_before_database_use(self):
        sidecar = Path(str(self.path) + "-wal")
        sidecar.write_bytes(b"sidecar")
        sidecar.chmod(0o644)
        with self.assertRaises(PermissionError):
            self.store.sync_findings([self.finding], now=100)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM admin_alerts").fetchone()[0], 0)

    def test_resolution_then_recurrence_starts_new_episode(self):
        self.assertEqual(self.store.sync_findings([self.finding], now=100), 1)
        self.assertEqual(self.store.sync_findings([], now=110), 0)
        self.assertEqual(self.store.sync_findings([self.finding], now=120), 1)
        with closing(sqlite3.connect(self.path)) as db:
            episodes = db.execute("SELECT DISTINCT episode_id FROM admin_alert_deliveries").fetchall()
            state = db.execute("SELECT state FROM admin_alerts").fetchone()[0]
        self.assertEqual(len(episodes), 2)
        self.assertEqual(state, "active")

    def test_resolving_finding_cancels_pending_and_invalidates_leased_delivery(self):
        self.store.sync_findings([self.finding], now=100)
        self.assertEqual(self.store.sync_findings([], now=101), 0)
        self.assertIsNone(self.store.claim(now=101))

        self.store.sync_findings([self.finding], now=102)
        leased = self.store.claim(now=102)
        self.assertIsNotNone(leased)
        self.store.sync_findings([], now=103)
        self.assertFalse(self.store.finish(leased["id"], leased["lease_token"], delivered=True, now=104))
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT state FROM admin_alert_deliveries WHERE id=?",
                                        (leased["id"],)).fetchone()[0], "canceled")

    def test_failed_read_leaves_existing_persistent_delivery_untouched(self):
        self.store.sync_findings([self.finding], now=100)
        missing_log = Path(self.temp.name) / "missing-access-log.sqlite"
        log_store = type("LogStore", (), {
            "path": str(missing_log), "retention_days": 7,
            "_current_day": staticmethod(lambda: "2026-11-26"),
        })()
        thresholds = {
            "window_hours": 24, "max_requests_per_ip": 1000, "max_error_ratio": 0.5,
            "max_distinct_schools": 50, "min_requests": 20, "max_status_errors": 100,
        }
        with self.assertRaises(OSError):
            run_persistent_once(log_store, self.store, thresholds,
                                "https://discord.com/api/webhooks/123/token", b"s" * 32,
                                enabled=True, now=101)
        delivery = self.store.claim(now=101)
        self.assertIsNotNone(delivery)
        self.assertEqual(delivery["payload"], {"kind": "status_errors", "status_group": "404"})

    def test_result_and_state_row_limits_fail_without_partial_reservation(self):
        from unittest.mock import patch

        other = {**self.finding, "client_ip": "203.0.113.8"}
        with patch("backend.admin_alert_store._MAX_FINDINGS", 1):
            with self.assertRaises(ValueError):
                self.store.sync_findings([self.finding, other], now=100)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM admin_alerts").fetchone()[0], 0)

        with patch("backend.admin_alert_store._MAX_STORE_ROWS", 0):
            with self.assertRaises(ValueError):
                self.store.sync_findings([self.finding], now=100)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM admin_alerts").fetchone()[0], 0)

    def test_lease_survives_restart_and_expiry_allows_retry(self):
        self.store.sync_findings([self.finding], now=100)
        delivery = self.store.claim(now=100, lease_seconds=10)
        self.assertEqual(delivery["attempt"], 1)
        restarted = AdminAlertStore(self.path, self.key)
        self.assertIsNone(restarted.claim(now=105))
        retried_lease = restarted.claim(now=110, lease_seconds=10)
        self.assertEqual(retried_lease["id"], delivery["id"])
        self.assertEqual(retried_lease["attempt"], 2)
        self.assertFalse(restarted.finish(delivery["id"], delivery["lease_token"], delivered=True, now=111))
        self.assertTrue(restarted.finish(retried_lease["id"], retried_lease["lease_token"],
                                         delivered=False, retryable=True, now=111))
        self.assertIsNone(restarted.claim(now=230))
        retry = restarted.claim(now=231, lease_seconds=10)
        self.assertEqual(retry["attempt"], 3)
        self.assertTrue(restarted.finish(retry["id"], retry["lease_token"], delivered=True, now=172))

    def test_nonretryable_failure_and_attempt_limit_stop_claims(self):
        self.store.sync_findings([self.finding], now=0)
        first = self.store.claim(now=0, lease_seconds=1)
        self.assertTrue(self.store.finish(first["id"], first["lease_token"], delivered=False,
                                          retryable=False, now=0.5))
        self.assertIsNone(self.store.claim(now=1))

        self.store.sync_findings([], now=2)
        self.store.sync_findings([self.finding], now=3)
        now = 3
        for attempt in range(1, 7):
            item = self.store.claim(now=now, lease_seconds=1)
            self.assertEqual(item["attempt"], attempt)
            self.assertTrue(self.store.finish(item["id"], item["lease_token"], delivered=False,
                                              retryable=True, now=now + 0.5))
            now += (60 * (2 ** (attempt - 1))) + 1
        self.assertIsNone(self.store.claim(now=now))

    def test_prune_removes_only_old_terminal_deliveries(self):
        self.store.sync_findings([self.finding], now=0)
        delivery = self.store.claim(now=0, lease_seconds=100000)
        self.assertTrue(self.store.finish(delivery["id"], delivery["lease_token"], delivered=True, now=1))
        self.assertEqual(self.store.prune(now=1000, retention_seconds=100), 1)
        self.assertIsNone(self.store.claim(now=1001))


if __name__ == "__main__":
    unittest.main()
