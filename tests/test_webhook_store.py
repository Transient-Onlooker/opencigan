import sqlite3
import json
import tempfile
import unittest
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

from backend.webhook_store import WebhookStore
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

    def test_rejects_invalid_external_inputs(self):
        with self.assertRaises(ValueError):
            self.store.create("2:예시학교", True, 1, "https://discord.com/api/webhooks/123/secret")
        with self.assertRaises(ValueError):
            self.store.enqueue(self.subscription["id"], "../bad", b'{}')
        with self.assertRaises(ValueError):
            self.store.enqueue(self.subscription["id"], "evt", b'not json')

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
