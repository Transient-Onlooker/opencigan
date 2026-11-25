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
from backend.webhook_worker import deliver_next, run_worker
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

    def test_observed_change_requires_every_filter_and_matching_class(self):
        identifier, token = self.subscription["id"], self.subscription["token"]
        matching = {"subject": "수학", "teacher": "김", "weekday": 1, "period": 1, "type": "changed"}
        before = {"subject": "수학", "teacher": "박"}
        after = {"subject": "과학", "teacher": "김"}
        for index, (key, value) in enumerate((("subject", "영어"), ("teacher", "이"), ("weekday", 2), ("period", 2), ("type", "added")), 1):
            with self.subTest(filter=key):
                self.store.update_filters(identifier, token, {**matching, key: value})
                with closing(self.store._connect()) as db:
                    enqueue_observed_change(db, "2:예시학교", 2, 3, "2026-11-16", 1, "changed", before, after, index, 100)
                self.assertEqual(self.store.deliveries(identifier, token), [])
        self.store.update_filters(identifier, token, matching)
        with closing(self.store._connect()) as db:
            enqueue_observed_change(db, "2:예시학교", 2, 4, "2026-11-16", 1, "changed", before, after, 6, 100)
            enqueue_observed_change(db, "2:다른학교", 2, 3, "2026-11-16", 1, "changed", before, after, 7, 100)
            self.assertEqual(self.store.deliveries(identifier, token), [])
            enqueue_observed_change(db, "2:예시학교", 2, 3, "2026-11-16", 1, "changed", before, after, 8, 100)
        self.assertEqual([item["event_id"] for item in self.store.deliveries(identifier, token)], ["change_8"])

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

    def test_retry_waits_for_provider_delay_above_backoff(self):
        self.store.enqueue(self.subscription["id"], "rate_limited", b'{}', now=10)
        claim = self.store.claim(now=10)
        self.store.finish(claim["id"], claim["leaseToken"],
                          {"delivered": False, "retryable": True, "status": 429, "retryAfter": 61}, now=10)
        self.assertIsNone(self.store.claim(now=70))
        self.assertEqual(self.store.claim(now=71)["attempt"], 2)

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

    def test_idle_worker_prunes_expired_delivery_without_new_events(self):
        from unittest.mock import Mock
        identifier = self.subscription["id"]
        self.store.enqueue(identifier, "finished", b'{}', now=100)
        claim = self.store.claim(now=100)
        self.store.finish(claim["id"], claim["leaseToken"], {"delivered": True, "retryable": False}, now=100)
        stop = Mock()
        stop.is_set.side_effect = [False, True]
        with patch("backend.webhook_store.time.time", return_value=100 + 30 * 24 * 60 * 60 + 1):
            run_worker(self.store, stop)
        stop.wait.assert_called_once_with(2)
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

    def test_global_capacity_recovers_after_expired_history_is_pruned(self):
        identifier = self.subscription["id"]
        with patch("backend.webhook_store.MAX_DELIVERY_RECORDS", 1):
            self.assertTrue(self.store.enqueue(identifier, "finished", b'{}', now=100))
            claim = self.store.claim(now=100)
            self.assertTrue(self.store.finish(claim["id"], claim["leaseToken"],
                                              {"delivered": True, "retryable": False}, now=100))
            self.assertFalse(self.store.enqueue(identifier, "new", b'{}', now=101))
            self.assertIsNone(self.store.claim(now=100 + 30 * 24 * 60 * 60 + 1))
            self.assertTrue(self.store.enqueue(identifier, "new", b'{}', now=100 + 30 * 24 * 60 * 60 + 2))

    def test_payload_budget_rejects_new_delivery_without_deleting_existing_rows(self):
        identifier = self.subscription["id"]
        self.assertTrue(self.store.enqueue(identifier, "existing", b'{}', now=100))
        with patch("backend.webhook_store.MAX_DELIVERY_PAYLOAD_BYTES", 1):
            self.assertFalse(self.store.enqueue(identifier, "existing", b'{"replacement":true}', now=101))
            self.assertFalse(self.store.enqueue(identifier, "new", b'{"x":1}', now=101))
        with closing(self.store._connect()) as db:
            row = db.execute("SELECT event_id, body FROM webhook_deliveries").fetchone()
            self.assertEqual((row["event_id"], row["body"]), ("existing", b'{}'))

    def test_payload_budget_applies_to_test_notifications(self):
        identifier, token = self.subscription["id"], self.subscription["token"]
        with patch("backend.webhook_store.MAX_DELIVERY_PAYLOAD_BYTES", 1):
            self.assertFalse(self.store.enqueue_test(identifier, token, now=100))
        self.assertEqual(self.store.deliveries(identifier, token), [])
        with closing(self.store._connect()) as db:
            self.assertIsNone(db.execute("SELECT last_test_at FROM webhook_subscriptions WHERE id=?", (identifier,)).fetchone()[0])

    def test_payload_budget_rejection_preserves_history_and_counts_dropped_event(self):
        history = HistoryStore(self.path)
        identifier, token = self.subscription["id"], self.subscription["token"]
        base = datetime.now(timezone.utc)
        lesson = {"grade": 2, "class": 3, "date": "2026-11-16", "period": 1, "subject": "수학", "teacher": "김"}
        history.observe("2:예시학교", "2026-11-16", [lesson], base)
        with patch("backend.webhook_store.MAX_DELIVERY_PAYLOAD_BYTES", 1):
            history.observe("2:예시학교", "2026-11-16", [{**lesson, "subject": "과학"}], base + timedelta(seconds=1))
        changes = history.list("2:예시학교", "2026-11-16")["changes"]
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0]["after"]["subject"], "과학")
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT subject FROM snapshot_lessons WHERE school=? AND week=?",
                                        ("2:예시학교", "2026-11-16")).fetchone()[0], "과학")
        self.assertEqual(self.store.get(identifier, token)["dropped_events"], 1)
        self.assertEqual(self.store.deliveries(identifier, token), [])

    def test_observed_changes_reuse_byte_total_in_same_transaction(self):
        identifier, token = self.subscription["id"], self.subscription["token"]
        lesson = {"subject": "수학", "teacher": "김"}
        queries = []
        with patch("backend.webhook_store.MAX_DELIVERY_PAYLOAD_BYTES", 1), closing(self.store._connect()) as db:
            db.set_trace_callback(queries.append)
            db.execute("BEGIN IMMEDIATE")
            transaction_bytes = []
            for change_id in (1, 2):
                enqueue_observed_change(db, "2:예시학교", 2, 3, "2026-11-16", 1, "changed",
                                        lesson, lesson, change_id, 100, transaction_bytes)
            db.execute("COMMIT")
        self.assertEqual(self.store.get(identifier, token)["dropped_events"], 2)
        self.assertEqual(sum("SUM(length(body))" in query for query in queries), 1)

    def test_observed_changes_update_reused_byte_total_after_insert(self):
        identifier, token = self.subscription["id"], self.subscription["token"]
        lesson = {"subject": "수학", "teacher": "김"}
        with closing(self.store._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            transaction_bytes = []
            enqueue_observed_change(db, "2:예시학교", 2, 3, "2026-11-16", 1, "changed",
                                    lesson, lesson, 1, 100, transaction_bytes)
            self.assertGreater(transaction_bytes[0], 0)
            with patch("backend.webhook_store.MAX_DELIVERY_PAYLOAD_BYTES", transaction_bytes[0]):
                enqueue_observed_change(db, "2:예시학교", 2, 3, "2026-11-16", 1, "changed",
                                        lesson, lesson, 2, 100, transaction_bytes)
            db.execute("COMMIT")
        self.assertEqual(self.store.get(identifier, token)["dropped_events"], 1)
        self.assertEqual(len(self.store.deliveries(identifier, token)), 1)

    def test_payload_budget_is_atomic_across_concurrent_insertions(self):
        identifier = self.subscription["id"]
        with patch("backend.webhook_store.MAX_DELIVERY_PAYLOAD_BYTES", 3), ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda event_id: self.store.enqueue(identifier, event_id, b'{}', now=100),
                                    ("first", "second")))
        self.assertEqual(sum(results), 1)
        with closing(self.store._connect()) as db:
            self.assertEqual(db.execute("SELECT SUM(length(body)) FROM webhook_deliveries").fetchone()[0], 2)

    def test_payload_budget_recovers_after_expired_records_are_pruned(self):
        identifier = self.subscription["id"]
        with patch("backend.webhook_store.MAX_DELIVERY_PAYLOAD_BYTES", 2):
            self.assertTrue(self.store.enqueue(identifier, "finished", b'{}', now=100))
            claim = self.store.claim(now=100)
            self.assertTrue(self.store.finish(claim["id"], claim["leaseToken"],
                                              {"delivered": True, "retryable": False}, now=100))
            self.assertFalse(self.store.enqueue(identifier, "new", b'{}', now=101))
            self.assertIsNone(self.store.claim(now=100 + 30 * 24 * 60 * 60 + 1))
            self.assertTrue(self.store.enqueue(identifier, "new", b'{}', now=100 + 30 * 24 * 60 * 60 + 2))

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

    def test_teacher_filter_accepts_null_and_matches_previous_teacher(self):
        history = HistoryStore(self.path)
        self.store.update_filters(self.subscription['id'], self.subscription['token'], {'teacher': '김'})
        base = datetime.now(timezone.utc)
        lesson = {"grade": 2, "class": 3, "date": "2026-11-16", "period": 1, "subject": "수학", "teacher": None}
        history.observe("2:예시학교", "2026-11-16", [lesson], base)
        history.observe("2:예시학교", "2026-11-16", [{**lesson, "teacher": "김"}], base + timedelta(seconds=1))
        self.assertIsNotNone(self.store.claim(now=base.timestamp() + 30))
        history.observe("2:예시학교", "2026-11-16", [lesson], base + timedelta(seconds=2))
        self.assertIsNotNone(self.store.claim(now=base.timestamp() + 30))
        self.assertEqual(len(history.list("2:예시학교", "2026-11-16")["changes"]), 2)

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
