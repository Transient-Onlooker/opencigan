import sqlite3
import json
import tempfile
import unittest
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from backend.webhook_store import WebhookStore, enqueue_observed_change, quiet_until
from backend.webhook_worker import deliver_next
from backend.history import HistoryStore


class WebhookStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "webhooks.sqlite"
        self.store = WebhookStore(self.path)
        self.subscription = self.store.create("2:예시학교", 2, 3, "https://discord.com/api/webhooks/123/secret")

    def test_management_token_is_hashed_and_delete_removes_pending(self):
        identifier, token = self.subscription["id"], self.subscription["token"]
        with closing(sqlite3.connect(self.path)) as db:
            stored = db.execute("SELECT token_hash FROM webhook_subscriptions").fetchone()[0]
        self.assertNotEqual(stored, token)
        self.assertIsNone(self.store.get(identifier, "incorrect"))
        self.assertFalse(self.store.delete(identifier, "incorrect"))
        self.assertEqual(self.store.get(identifier, token)["classroom"], 3)
        self.store.enqueue(identifier, "evt_1", b'{}', now=100)
        self.assertTrue(self.store.delete(identifier, token))
        self.assertIsNone(self.store.claim(now=100))

    def test_deduplication_concurrent_claim_and_expired_lease(self):
        identifier = self.subscription["id"]
        self.assertTrue(self.store.enqueue(identifier, "evt_1", b'{}', now=100))
        self.assertFalse(self.store.enqueue(identifier, "evt_1", b'{}', now=100))
        with ThreadPoolExecutor(max_workers=2) as pool:
            claims = list(pool.map(lambda _: self.store.claim(now=100), range(2)))
        first = next(claim for claim in claims if claim)
        self.assertEqual(sum(claim is not None for claim in claims), 1)
        self.assertIsNone(self.store.claim(now=159))
        second = self.store.claim(now=160)
        self.assertNotEqual(first["leaseToken"], second["leaseToken"])
        self.assertFalse(self.store.finish(first["id"], first["leaseToken"], {"delivered": True, "retryable": False}, now=161))
        self.assertTrue(self.store.finish(second["id"], second["leaseToken"], {"delivered": True, "retryable": False, "status": 204}, now=161))
        self.assertIsNone(self.store.claim(now=1000))

    def test_retry_and_permanent_failure(self):
        self.store.enqueue(self.subscription["id"], "evt_2", b'{"ok":true}', now=10)
        claim = self.store.claim(now=10)
        self.assertTrue(self.store.finish(claim["id"], claim["leaseToken"], {"delivered": False, "retryable": True, "status": 429, "retryAfter": 120}, now=10))
        self.assertIsNone(self.store.claim(now=129))
        claim = self.store.claim(now=130)
        self.assertEqual(claim["attempt"], 2)
        self.store.finish(claim["id"], claim["leaseToken"], {"delivered": False, "retryable": False, "status": 400}, now=130)
        self.assertIsNone(self.store.claim(now=10000))

    def test_quiet_hours_defer_due_delivery_and_allow_test_messages(self):
        kst = timezone(timedelta(hours=9))
        instant = lambda day, hour, minute=0: datetime(2026, 11, day, hour, minute, tzinfo=kst).timestamp()
        quiet = {"start": "22:00", "end": "07:00"}
        self.assertEqual(quiet_until(instant(16, 23), quiet), instant(17, 7))
        self.assertEqual(quiet_until(instant(17, 6, 59), quiet), instant(17, 7))
        self.assertIsNone(quiet_until(instant(17, 7), quiet))
        self.assertEqual(quiet_until(instant(16, 13), {"start": "12:00", "end": "14:00"}), instant(16, 14))
        identifier, token = self.subscription["id"], self.subscription["token"]
        self.assertTrue(self.store.update_filters(identifier, token, {"quietHours": quiet}))
        self.store.enqueue(identifier, "event_1", b'{}', now=instant(16, 21))
        test_id = self.store.enqueue_test(identifier, token, now=instant(16, 23))
        test = self.store.claim(now=instant(16, 23))
        self.assertEqual(test["event_id"], test_id)
        self.store.finish(test["id"], test["leaseToken"], {"delivered": True, "retryable": False}, now=instant(16, 23))
        self.assertIsNone(self.store.claim(now=instant(17, 6)))
        self.assertEqual(self.store.claim(now=instant(17, 7))["event_id"], "event_1")

    def test_quiet_hours_validation(self):
        identifier, token = self.subscription["id"], self.subscription["token"]
        for value in ({"start": "07:00", "end": "07:00"}, {"start": "24:00", "end": "07:00"}, {"start": "7:00", "end": "08:00"}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.store.update_filters(identifier, token, {"quietHours": value})

    def test_expired_crashes_stop_after_six_attempts_and_old_results_expire(self):
        self.store.enqueue(self.subscription["id"], "crash", b'{}', now=100)
        for attempt in range(6):
            claim = self.store.claim(now=100 + 60 * attempt)
            self.assertEqual(claim["attempt"], attempt + 1)
        self.assertIsNone(self.store.claim(now=460))
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT state FROM webhook_deliveries").fetchone()[0], "failed")
        self.store.claim(now=460 + 30 * 24 * 60 * 60 + 1)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM webhook_deliveries").fetchone()[0], 0)

    def test_queue_limit_drops_new_event_without_breaking_history(self):
        with patch("backend.webhook_store.MAX_PENDING_PER_SUBSCRIPTION", 1):
            self.assertTrue(self.store.enqueue(self.subscription["id"], "first", b'{}', now=1))
            self.assertFalse(self.store.enqueue(self.subscription["id"], "second", b'{}', now=1))
            history = HistoryStore(self.path)
            now = datetime.now(timezone.utc)
            lesson = {"grade": 2, "class": 3, "date": "2026-11-16", "period": 1, "subject": "수학", "teacher": "김"}
            history.observe("2:예시학교", "2026-11-16", [lesson], now)
            history.observe("2:예시학교", "2026-11-16", [{**lesson, "subject": "과학"}], now + timedelta(seconds=1))
            self.assertEqual(len(history.list("2:예시학교", "2026-11-16")["changes"]), 1)
            self.assertEqual(self.store.get(self.subscription["id"], self.subscription["token"])["dropped_events"], 1)
            with closing(sqlite3.connect(self.path)) as db:
                self.assertEqual(db.execute("SELECT COUNT(*) FROM webhook_deliveries").fetchone()[0], 1)

    def test_duplicate_observation_does_not_count_as_dropped_when_queue_is_full(self):
        identifier, token = self.subscription["id"], self.subscription["token"]
        lesson = {"subject": "수학", "teacher": "김"}
        with patch("backend.webhook_store.MAX_PENDING_PER_SUBSCRIPTION", 1), closing(self.store._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            for change_id in (1, 1, 2):
                enqueue_observed_change(db, "2:예시학교", 2, 3, "2026-11-16", 1, "changed", lesson, lesson, change_id, 100)
            db.execute("COMMIT")
        self.assertEqual(self.store.get(identifier, token)["dropped_events"], 1)
        self.assertEqual([item["event_id"] for item in self.store.deliveries(identifier, token)], ["change_1"])

    def test_global_capacity_blocks_all_insertion_paths_without_removing_history(self):
        identifier, token = self.subscription["id"], self.subscription["token"]
        other = self.store.create("2:예시학교", 2, 4, "https://discord.com/api/webhooks/456/token")
        with patch("backend.webhook_store.MAX_DELIVERY_RECORDS", 1):
            self.assertTrue(self.store.enqueue(identifier, "existing", b'{}', now=100))
            self.assertFalse(self.store.enqueue(other["id"], "new", b'{}', now=100))
            self.assertFalse(self.store.enqueue_test(other["id"], other["token"], now=100))
            lesson = {"subject": "수학", "teacher": "김"}
            with closing(self.store._connect()) as db:
                db.execute("BEGIN IMMEDIATE")
                enqueue_observed_change(db, "2:예시학교", 2, 3, "2026-11-16", 1, "changed", lesson, lesson, 7, 100)
                db.execute("COMMIT")
            self.assertEqual(self.store.get(identifier, token)["dropped_events"], 1)
            self.assertEqual([item["event_id"] for item in self.store.deliveries(identifier, token)], ["existing"])

    def test_global_capacity_is_atomic_across_subscriptions(self):
        other = self.store.create("2:예시학교", 2, 4, "https://discord.com/api/webhooks/456/token")
        with patch("backend.webhook_store.MAX_DELIVERY_RECORDS", 1), ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda sub: self.store.enqueue(sub["id"], "event", b'{}', now=100),
                                    (self.subscription, other)))
        self.assertEqual(sum(results), 1)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM webhook_deliveries").fetchone()[0], 1)

    def test_rejects_invalid_external_inputs(self):
        with self.assertRaises(ValueError):
            self.store.create("2:예시학교", True, 1, "https://discord.com/api/webhooks/123/secret")
        with self.assertRaises(ValueError):
            self.store.enqueue(self.subscription["id"], "../bad", b'{}')
        with self.assertRaises(ValueError):
            self.store.enqueue(self.subscription["id"], "evt", b'not json')

    def test_rotate_management_token_revokes_old_preserves_subscription_and_queue(self):
        identifier, old_token = self.subscription["id"], self.subscription["token"]
        other = self.store.create("2:예시학교", 2, 4, "https://discord.com/api/webhooks/456/other")
        other_id, other_token = other["id"], other["token"]

        # Set filters and enqueue delivery on original subscription
        filters = {"period": 2, "subject": "수학"}
        self.assertTrue(self.store.update_filters(identifier, old_token, filters))
        self.assertTrue(self.store.enqueue(identifier, "evt_pending_1", b'{"msg":"hello"}', now=100))

        # Wrong token rotation rejected
        new_token = 'b' * 43
        self.assertIsNone(self.store.rotate(identifier, "wrong_token_value_that_has_43_chars_abcdef", new_token))
        self.assertIsNone(self.store.rotate("non_existent_sub_1234567", old_token, new_token))
        with self.assertRaises(ValueError):
            self.store.rotate(identifier, old_token, old_token)

        # Rotate token
        rotated = self.store.rotate(identifier, old_token, new_token)
        self.assertEqual(rotated, {"rotated": True})
        self.assertNotEqual(old_token, new_token)
        self.assertEqual(len(new_token), 43)
        with closing(sqlite3.connect(self.path)) as db:
            stored = db.execute("SELECT token_hash FROM webhook_subscriptions WHERE id=?", (identifier,)).fetchone()[0]
        self.assertNotEqual(stored, new_token)

        # Old token immediately revoked
        self.assertIsNone(self.store.get(identifier, old_token))
        self.assertFalse(self.store.update_filters(identifier, old_token, {"period": 3}))
        self.assertIsNone(self.store.deliveries(identifier, old_token))
        self.assertIsNone(self.store.rotate(identifier, old_token, 'c' * 43))

        # New token accepted, filters preserved
        sub = self.store.get(identifier, new_token)
        self.assertIsNotNone(sub)
        self.assertEqual(sub["filters"], filters)
        self.assertEqual(sub["classroom"], 3)

        # Queued deliveries preserved and deliverable
        deliveries = self.store.deliveries(identifier, new_token)
        self.assertEqual(len(deliveries), 1)
        self.assertEqual(deliveries[0]["event_id"], "evt_pending_1")
        claim = self.store.claim(now=100)
        self.assertIsNotNone(claim)
        self.assertEqual(claim["event_id"], "evt_pending_1")
        self.assertTrue(self.store.finish(claim["id"], claim["leaseToken"], {"delivered": True, "retryable": False}, now=101))

        # Other subscription completely unaffected
        other_sub = self.store.get(other_id, other_token)
        self.assertIsNotNone(other_sub)
        self.assertEqual(other_sub["classroom"], 4)

    def test_worker_retries_then_delivers_without_changing_event_id(self):
        self.store.enqueue(self.subscription["id"], "stable_event", b'{"text":"example"}', now=100)
        calls = []
        def sender(url, body, secret, event_id):
            calls.append((event_id, body, secret))
            return {"delivered": len(calls) == 2, "retryable": len(calls) == 1, "status": 204 if len(calls) == 2 else 503, "retryAfter": None}
        self.assertTrue(deliver_next(self.store, now=100, sender=sender))
        self.assertFalse(deliver_next(self.store, now=129, sender=sender))
        self.assertTrue(deliver_next(self.store, now=130, sender=sender))
        self.assertEqual(calls[0], calls[1])
        self.assertFalse(deliver_next(self.store, now=1000, sender=sender))

    def test_observed_changes_enqueue_only_matching_class_atomically(self):
        history = HistoryStore(self.path)
        other = self.store.create("2:예시학교", 2, 4, "https://chat.googleapis.com/v1/spaces/abc/messages?key=K&token=T")
        base = datetime.now(timezone.utc)
        lesson = {"grade": 2, "class": 3, "date": "2026-11-16", "period": 1, "subject": "수학", "teacher": "김"}
        history.observe("2:예시학교", "2026-11-16", [lesson], base)
        self.assertIsNone(self.store.claim(now=base.timestamp() + 30))
        modified = {**lesson, "subject": "<users/all>@everyone"}
        history.observe("2:예시학교", "2026-11-16", [modified], base + timedelta(seconds=1))
        delivery = self.store.claim(now=base.timestamp() + 30)
        payload = json.loads(delivery["body"])
        self.assertEqual(payload["allowed_mentions"], {"parse": []})
        self.assertNotIn("<users/all>", payload["content"])
        self.assertIsNone(self.store.claim(now=base.timestamp() + 30))
        self.assertIsNotNone(self.store.get(other["id"], other["token"]))
        self.assertEqual(len(history.list("2:예시학교", "2026-11-16")["changes"]), 1)
        history.observe("2:예시학교", "2026-11-16", [modified], base + timedelta(seconds=2))
        self.assertIsNone(self.store.claim(now=base.timestamp() + 30))

    def test_failed_enqueue_rolls_back_history_and_snapshot(self):
        history = HistoryStore(self.path)
        base = datetime.now(timezone.utc)
        lesson = {"grade": 2, "class": 3, "date": "2026-11-16", "period": 1, "subject": "수학", "teacher": "김"}
        history.observe("2:예시학교", "2026-11-16", [lesson], base)
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("CREATE TRIGGER reject_queue BEFORE INSERT ON webhook_deliveries BEGIN SELECT RAISE(ABORT, 'test failure'); END")
            db.commit()
        with self.assertRaises(sqlite3.IntegrityError):
            history.observe("2:예시학교", "2026-11-16", [{**lesson, "subject": "과학"}], base + timedelta(seconds=1))
        self.assertEqual(history.list("2:예시학교", "2026-11-16")["changes"], [])
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("DROP TRIGGER reject_queue")
            db.commit()
        history.observe("2:예시학교", "2026-11-16", [{**lesson, "subject": "과학"}], base + timedelta(seconds=2))
        self.assertEqual(history.list("2:예시학교", "2026-11-16")["changes"][0]["before"]["subject"], "수학")
