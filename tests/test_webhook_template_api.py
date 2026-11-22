import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from backend.app import dispatch_request
from backend.history import HistoryStore
from backend.webhook_store import WebhookStore, enqueue_observed_change


class LegacySchemaTests(unittest.TestCase):
    def test_observed_change_compatible_before_template_migration(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "legacy.sqlite")
            with closing(sqlite3.connect(path)) as db:
                db.row_factory = sqlite3.Row
                db.executescript("""
                CREATE TABLE webhook_subscriptions (
                    id TEXT PRIMARY KEY, token_hash TEXT NOT NULL, school TEXT NOT NULL,
                    grade INTEGER NOT NULL, classroom INTEGER NOT NULL, destination TEXT NOT NULL,
                    provider TEXT NOT NULL, signing_secret BLOB NOT NULL, filters_json TEXT NOT NULL DEFAULT '{}'
                );
                CREATE TABLE webhook_deliveries (
                    id INTEGER PRIMARY KEY, subscription_id TEXT NOT NULL, event_id TEXT NOT NULL,
                    body BLOB NOT NULL, state TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0,
                    next_at REAL NOT NULL, UNIQUE(subscription_id, event_id)
                );
                """)
                db.execute("INSERT INTO webhook_subscriptions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                           ("a" * 24, "x", "2:Legacy School", 2, 3,
                            "https://discord.com/api/webhooks/1/secret", "discord", b"x", "{}"))
                db.commit()
                enqueue_observed_change(db, "2:Legacy School", 2, 3, "2026-11-16", 1, "changed",
                                         {"subject": "Math", "teacher": "Kim"},
                                         {"subject": "Science", "teacher": "Kim"}, 999, 10)
                self.assertEqual(db.execute("SELECT COUNT(*) FROM webhook_deliveries").fetchone()[0], 1)


class WebhookTemplateApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = str(Path(self.temp.name) / "history.sqlite")
        HistoryStore(self.path)
        self.payload = {"school": "2:Example School", "grade": 2, "class": 3,
                        "destination": "https://discord.com/api/webhooks/123/secret"}

    def request(self, method, path, payload=None, token=None):
        body = json.dumps(payload, ensure_ascii=False).encode() if payload is not None else None
        headers = {"Authorization": "Bearer " + token} if token else {}
        return dispatch_request(method, path, "", request_body=body, request_headers=headers)

    def test_template_api_is_authenticated_validated_and_resettable(self):
        with patch.dict("os.environ", {"OPENCIGAN_HISTORY_DB": self.path, "OPENCIGAN_WEBHOOKS_ENABLED": "1"}):
            _, _, body = self.request("POST", "/api/v1/webhooks", self.payload)
            created = json.loads(body)
            path = f"/api/v1/webhooks/{created['id']}/template"
            self.assertEqual(self.request("GET", path)[0], 401)
            self.assertEqual(self.request("PUT", path, {"template": "{unknown}", "discordEmbed": False}, created["token"])[0], 400)
            template = {"template": "{school} {period}교시 {before} → {after}", "discordEmbed": True}
            status, _, body = self.request("PUT", path, template, created["token"])
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(body)["template"], template["template"])
            self.assertEqual(self.request("DELETE", path, token=created["token"])[0], 200)
            self.assertIsNone(json.loads(self.request("GET", path, token=created["token"])[2])["template"])

    def test_template_update_rechecks_token_in_update_statement(self):
        with patch.dict("os.environ", {"OPENCIGAN_HISTORY_DB": self.path, "OPENCIGAN_WEBHOOKS_ENABLED": "1"}):
            _, _, body = self.request("POST", "/api/v1/webhooks", self.payload)
            created = json.loads(body)
            store = WebhookStore(self.path)
            original_render = __import__("backend.webhook_store", fromlist=["render_template"]).render_template

            def replace_token_during_validation(*args, **kwargs):
                rendered = original_render(*args, **kwargs)
                with closing(sqlite3.connect(self.path)) as db:
                    db.execute("UPDATE webhook_subscriptions SET token_hash=? WHERE id=?",
                               ("revoked", created["id"]))
                    db.commit()
                return rendered

            with patch("backend.webhook_store.render_template", side_effect=replace_token_during_validation):
                result = store.update_template(created["id"], created["token"], "{school}")
            self.assertIsNone(result)
            with closing(sqlite3.connect(self.path)) as db:
                self.assertIsNone(db.execute("SELECT template_json FROM webhook_subscriptions WHERE id=?",
                                             (created["id"],)).fetchone()[0])

    def test_preview_does_not_enqueue_or_send_and_observed_change_uses_saved_template(self):
        with patch.dict("os.environ", {"OPENCIGAN_HISTORY_DB": self.path, "OPENCIGAN_WEBHOOKS_ENABLED": "1"}):
            _, _, body = self.request("POST", "/api/v1/webhooks", self.payload)
            created = json.loads(body)
            base_path = f"/api/v1/webhooks/{created['id']}"
            spec = {"template": "{school} {grade} {classroom} {type}: {before} → {after}", "discordEmbed": False}
            status, _, body = self.request("POST", base_path + "/template/preview", spec, created["token"])
            self.assertEqual(status, 200)
            preview_payload = json.loads(body)["payload"]
            self.assertIn("content", preview_payload)
            self.assertEqual(WebhookStore(self.path).deliveries(created["id"], created["token"]), [])
            self.assertEqual(self.request("PUT", base_path + "/template", spec, created["token"])[0], 200)

            history = HistoryStore(self.path)
            now = datetime.now(timezone.utc)
            lesson = {"grade": 2, "class": 3, "date": "2026-11-16", "period": 1, "subject": "Math", "teacher": "Kim"}
            history.observe(self.payload["school"], "2026-11-16", [lesson], now)
            history.observe(self.payload["school"], "2026-11-16", [{**lesson, "subject": "Science"}], now + timedelta(seconds=1))
            delivery = WebhookStore(self.path).claim(now=now.timestamp() + 10)
            self.assertEqual(json.loads(delivery["body"])["content"], "Example School 2 3 changed: Math · Kim → Science · Kim")

    def test_disabled_by_default_for_template_routes(self):
        with patch.dict("os.environ", {"OPENCIGAN_HISTORY_DB": self.path, "OPENCIGAN_WEBHOOKS_ENABLED": ""}):
            self.assertEqual(self.request("GET", "/api/v1/webhooks/" + "a" * 24 + "/template")[0], 503)

    def test_oversized_render_falls_back_without_aborting_history_recording(self):
        with patch.dict("os.environ", {"OPENCIGAN_HISTORY_DB": self.path, "OPENCIGAN_WEBHOOKS_ENABLED": "1"}):
            _, _, body = self.request("POST", "/api/v1/webhooks", self.payload)
            created = json.loads(body)
            store = WebhookStore(self.path)
            self.assertIsNotNone(store.update_template(created["id"], created["token"], "{before}"))
            history = HistoryStore(self.path)
            now = datetime.now(timezone.utc)
            long_lesson = {"grade": 2, "class": 3, "date": "2026-11-16", "period": 1,
                           "subject": "x" * 1801, "teacher": ""}
            short_lesson = {**long_lesson, "subject": "Short"}
            history.observe(self.payload["school"], "2026-11-16", [long_lesson], now)
            history.observe(self.payload["school"], "2026-11-16", [short_lesson], now + timedelta(seconds=1))
            self.assertEqual(len(history.list(self.payload["school"], "2026-11-16")["changes"]), 1)
            delivery = store.claim(now=now.timestamp() + 10)
            rendered = json.loads(delivery["body"])["content"]
            self.assertTrue(rendered.startswith("Example School"))
            self.assertEqual(len(rendered), 1800)


if __name__ == "__main__":
    unittest.main()
