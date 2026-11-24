import sqlite3
import os
import tempfile
import unittest
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
from datetime import date, datetime, timedelta, timezone

from backend.scheduled_store import ScheduledStore
from backend.scheduled_lessons import scheduled_event_id
from backend.history import HistoryStore
from backend.webhook_store import WebhookStore


class ScheduledStoreTests(unittest.TestCase):
    def setUp(self):
        root = Path.home() / "AppData" / "Local" / "Temp" if os.name == "nt" else None
        self.temp = tempfile.TemporaryDirectory(dir=root)
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "scheduled.sqlite"
        self.webhooks = WebhookStore(self.path)
        self.subscription = self.webhooks.create(
            "2:Example School", 2, 3, "https://discord.com/api/webhooks/123/secret"
        )
        self.store = ScheduledStore(self.path)

    def test_construction_is_inert_and_settings_require_subscription_token(self):
        missing = Path(self.temp.name) / "not-created.sqlite"
        ScheduledStore(missing)
        self.assertFalse(missing.exists())
        with self.assertRaises(sqlite3.OperationalError):
            ScheduledStore(missing).get_schedule("a" * 24, "b" * 43)
        self.assertFalse(missing.exists())

        identifier, token = self.subscription["id"], self.subscription["token"]
        self.assertIsNone(self.store.set_schedule(identifier, "wrong", "daily_summary", "07:30"))
        self.assertIsNone(self.store.get_schedule(identifier, "wrong"))
        self.assertEqual(
            self.store.set_schedule(identifier, token, "subject_prep", "07:25", "Chemistry"),
            {"mode": "subject_prep", "time_kst": "07:25", "subject": "Chemistry", "revision": 1},
        )
        self.assertEqual(self.store.get_schedule(identifier, token)["subject"], "Chemistry")
        self.assertEqual(self.store.set_schedule(identifier, token, "subject_prep", "07:25", "Chemistry")["revision"], 1)
        with closing(sqlite3.connect(self.path)) as db:
            stored = db.execute(
                "SELECT token_hash FROM webhook_subscriptions WHERE id=?", (identifier,)
            ).fetchone()[0]
        self.assertNotEqual(stored, token)

    def test_due_enqueue_is_atomic_idempotent_and_survives_restart(self):
        identifier, token = self.subscription["id"], self.subscription["token"]
        revision = self.store.set_schedule(identifier, token, "daily_summary", "07:30")["revision"]
        body = b'{"text":"summary"}'
        with ThreadPoolExecutor(max_workers=6) as pool:
            inserted = list(pool.map(
                lambda _: self.store.enqueue_due(
                    identifier, revision, "2026-11-23", body, 1795390200.0
                ),
                range(6),
            ))
        self.assertEqual(sum(inserted), 1)

        restarted = ScheduledStore(self.path)
        self.assertFalse(restarted.enqueue_due(
            identifier, revision, "2026-11-23", body, 1795390200.0
        ))
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute(
                "SELECT COUNT(*) FROM webhook_deliveries WHERE subscription_id=?", (identifier,)
            ).fetchone()[0], 1)
            self.assertEqual(db.execute(
                "SELECT next_at FROM webhook_deliveries WHERE subscription_id=?", (identifier,)
            ).fetchone()[0], 1795390200.0)
            self.assertEqual(db.execute("SELECT event_id FROM webhook_deliveries WHERE subscription_id=?", (identifier,)).fetchone()[0],
                             scheduled_event_id(identifier, "daily_summary", date(2026, 11, 23)))

    def test_schedule_change_cannot_requeue_leased_or_completed_day(self):
        for finish in (False, True):
            sub = self.webhooks.create("2:Example School", 2, 3, "https://discord.com/api/webhooks/123/secret")
            identifier, token = sub["id"], sub["token"]
            first = self.store.set_schedule(identifier, token, "daily_summary", "07:30")
            self.assertTrue(self.store.enqueue_due(identifier, first["revision"], "2026-11-23", b"{}", 100))
            delivery = self.webhooks.claim(now=100)
            self.assertIsNotNone(delivery)
            if finish:
                self.assertTrue(self.webhooks.finish(delivery["id"], delivery["leaseToken"],
                                                     {"delivered": True}, now=101))
            updated = self.store.set_schedule(identifier, token, "daily_summary", "08:30")
            self.assertFalse(self.store.enqueue_due(identifier, updated["revision"], "2026-11-23", b"{}", 200))

    def test_queue_limit_and_invalid_payload_do_not_reserve_occurrence(self):
        identifier, token = self.subscription["id"], self.subscription["token"]
        revision = self.store.set_schedule(identifier, token, "daily_summary", "07:30")["revision"]
        for body in (b"", b"not-json", b"x" * 65537):
            with self.assertRaises(ValueError):
                self.store.enqueue_due(identifier, revision, "2026-11-23", body, 100)
        self.assertTrue(self.webhooks.enqueue(identifier, "existing", b"{}", now=100))
        with patch("backend.scheduled_store.MAX_PENDING_PER_SUBSCRIPTION", 1):
            self.assertFalse(self.store.enqueue_due(identifier, revision, "2026-11-23", b"{}", 100))
        with patch("backend.webhook_store.MAX_DELIVERY_RECORDS", 1):
            self.assertFalse(self.store.enqueue_due(identifier, revision, "2026-11-23", b"{}", 100))
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM scheduled_occurrences").fetchone()[0], 0)

    def test_cancel_leased_prevents_retry_and_same_day_requeue(self):
        identifier, token = self.subscription["id"], self.subscription["token"]
        revision = self.store.set_schedule(identifier, token, "daily_summary", "07:30")["revision"]
        self.assertTrue(self.store.enqueue_due(identifier, revision, "2026-11-23", b"{}", 100))
        delivery = self.webhooks.claim(now=100)
        self.assertTrue(self.store.cancel_schedule(identifier, token))
        self.assertFalse(self.webhooks.finish(delivery["id"], delivery["leaseToken"],
                                              {"delivered": False, "retryable": True, "status": 500}, now=101))
        self.assertIsNone(self.webhooks.claim(now=200))
        updated = self.store.set_schedule(identifier, token, "daily_summary", "08:00")
        self.assertFalse(self.store.enqueue_due(identifier, updated["revision"], "2026-11-23", b"{}", 200))

    def test_canceled_queue_records_expire_under_existing_retention_policy(self):
        identifier, token = self.subscription["id"], self.subscription["token"]
        revision = self.store.set_schedule(identifier, token, "daily_summary", "07:30")["revision"]
        self.store.enqueue_due(identifier, revision, "2026-11-23", b"{}", 100)
        self.webhooks.claim(now=100)
        with patch("backend.scheduled_store.time.time", return_value=100):
            self.store.cancel_schedule(identifier, token)
        self.assertIsNone(self.webhooks.claim(now=100 + 30 * 24 * 60 * 60 + 1))
        self.assertEqual(self.webhooks.deliveries(identifier, token), [])

    def test_cleanup_keeps_active_delivery_and_expires_old_terminal_occurrences(self):
        identifier, token = self.subscription["id"], self.subscription["token"]
        revision = self.store.set_schedule(identifier, token, "daily_summary", "07:30")["revision"]
        self.assertTrue(self.store.enqueue_due(identifier, revision, "2026-09-01", b"{}", 100))
        self.assertEqual(self.store.prune_occurrences(date(2026, 11, 23)), 0)
        delivery = self.webhooks.claim(now=100)
        self.assertTrue(self.webhooks.finish(delivery["id"], delivery["leaseToken"], {"delivered": True}, now=101))
        self.assertEqual(self.store.prune_occurrences(date(2026, 11, 23)), 1)

    def test_noop_after_reschedule_replaces_canceled_occurrence(self):
        identifier, token = self.subscription["id"], self.subscription["token"]
        first = self.store.set_schedule(identifier, token, "subject_prep", "07:30", "체육")
        self.assertTrue(self.store.enqueue_due(identifier, first["revision"], "2026-11-23", b"{}", 100))
        updated = self.store.set_schedule(identifier, token, "subject_prep", "08:00", "수학")
        self.assertTrue(self.store.mark_noop(identifier, updated["revision"], "2026-11-23"))
        self.assertTrue(self.store.already_handled(identifier, "subject_prep", "2026-11-23"))
        self.assertFalse(self.store.enqueue_due(identifier, updated["revision"], "2026-11-23", b"{}", 200))

    def test_summary_mode_suppresses_immediate_changes_only_when_enabled(self):
        identifier, token = self.subscription["id"], self.subscription["token"]
        self.store.set_schedule(identifier, token, "daily_summary", "07:30")
        history = HistoryStore(self.path)
        now = datetime.now(timezone.utc)
        lesson = {"date": "2026-11-23", "grade": 2, "class": 3, "period": 1, "subject": "Math", "teacher": "Kim"}
        with patch.dict(os.environ, {"OPENCIGAN_SCHEDULER_ENABLED": ""}):
            history.observe("2:Example School", "2026-11-23", [lesson], now)
            history.observe("2:Example School", "2026-11-23", [{**lesson, "subject": "Science"}], now + timedelta(seconds=1))
        self.assertEqual(len(self.webhooks.deliveries(identifier, token)), 1)
        with patch.dict(os.environ, {"OPENCIGAN_SCHEDULER_ENABLED": "1"}):
            history.observe("2:Example School", "2026-11-23", [{**lesson, "subject": "Art"}], now + timedelta(seconds=2))
            self.assertEqual(len(self.webhooks.deliveries(identifier, token)), 1)
            self.store.set_schedule(identifier, token, "immediate", "07:30")
            history.observe("2:Example School", "2026-11-23", [{**lesson, "subject": "Music"}], now + timedelta(seconds=3))
        self.assertEqual(len(self.webhooks.deliveries(identifier, token)), 2)

    def test_cancel_and_change_keep_tombstones_and_cancel_pending_delivery(self):
        identifier, token = self.subscription["id"], self.subscription["token"]
        first = self.store.set_schedule(identifier, token, "daily_summary", "07:30")
        self.assertTrue(self.store.enqueue_due(
            identifier, first["revision"], "2026-11-23", b"{}", 100
        ))
        updated = self.store.set_schedule(identifier, token, "immediate", "08:00")
        self.assertEqual(updated["revision"], first["revision"] + 1)
        with closing(sqlite3.connect(self.path)) as db:
            state = db.execute("SELECT state FROM webhook_deliveries WHERE subscription_id=?", (identifier,)).fetchone()
            occurrence = db.execute(
                "SELECT state FROM scheduled_occurrences WHERE subscription_id=?", (identifier,)
            ).fetchone()[0]
        self.assertIsNone(state)
        self.assertEqual(occurrence, "canceled")
        self.assertFalse(self.store.enqueue_due(
            identifier, first["revision"], "2026-11-23", b"{}", 100
        ))

        self.assertTrue(self.store.cancel_schedule(identifier, token))
        self.assertIsNone(self.store.get_schedule(identifier, token))
        self.assertFalse(self.store.enqueue_due(
            identifier, updated["revision"], "2026-11-24", b"{}", 100
        ))
        next_setting = self.store.set_schedule(identifier, token, "daily_summary", "07:30")
        self.assertEqual(next_setting["revision"], updated["revision"] + 1)
        self.assertTrue(self.store.enqueue_due(
            identifier, next_setting["revision"], "2026-11-23", b"{}", 200
        ))

    def test_deleting_subscription_cascades_settings_occurrences_and_queue(self):
        identifier, token = self.subscription["id"], self.subscription["token"]
        revision = self.store.set_schedule(identifier, token, "daily_summary", "07:30")["revision"]
        self.store.enqueue_due(identifier, revision, "2026-11-23", b"{}", 100)
        self.assertTrue(self.webhooks.delete(identifier, token))
        with closing(sqlite3.connect(self.path)) as db:
            for table in ("scheduled_settings", "scheduled_occurrences", "webhook_deliveries"):
                self.assertEqual(db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], 0)

    def test_schedule_and_event_inputs_are_validated(self):
        identifier, token = self.subscription["id"], self.subscription["token"]
        for mode, time_kst, subject in (
            ("daily_summary", "7:30", None),
            ("unknown", "07:30", None),
            ("subject_prep", "07:30", " "),
            ("immediate", "07:30", "Chemistry"),
        ):
            with self.subTest(mode=mode, time_kst=time_kst, subject=subject):
                with self.assertRaises(ValueError):
                    self.store.set_schedule(identifier, token, mode, time_kst, subject)
        revision = self.store.set_schedule(identifier, token, "daily_summary", "07:30")["revision"]
        for scheduled_date, due_at in (("2026-02-30", 1), ("2026-11-23", float("nan"))):
            with self.subTest(scheduled_date=scheduled_date, due_at=due_at):
                with self.assertRaises(ValueError):
                    self.store.enqueue_due(identifier, revision, scheduled_date, b"{}", due_at)


if __name__ == "__main__":
    unittest.main()
