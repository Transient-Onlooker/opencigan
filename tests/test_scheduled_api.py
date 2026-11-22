import json
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from backend.app import dispatch_request
from backend.webhook_store import WebhookStore


class ScheduledApiTests(unittest.TestCase):
    def setUp(self):
        root = Path.home() / "AppData" / "Local" / "Temp" if os.name == "nt" else None
        self.directory = tempfile.TemporaryDirectory(dir=root)
        self.addCleanup(self.directory.cleanup)
        self.store = WebhookStore(Path(self.directory.name) / "history.sqlite")
        self.subscription = self.store.create("2:Example", 2, 3, "https://discord.com/api/webhooks/123/secret")
        self.path = f"/api/v1/webhooks/{self.subscription['id']}/schedule"

    def request(self, method, payload=None, token=None):
        body = json.dumps(payload).encode() if payload is not None else None
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        with patch("backend.app._webhook_store", return_value=self.store):
            return dispatch_request(method, self.path, "", request_body=body, request_headers=headers)

    def test_feature_is_disabled_by_default_without_creating_schedule_tables(self):
        with patch.dict(os.environ, {"OPENCIGAN_SCHEDULER_ENABLED": ""}):
            status, _, body = self.request("GET", token=self.subscription["token"])
        self.assertEqual((status, json.loads(body)["code"]), (503, "scheduler_disabled"))
        with closing(sqlite3.connect(self.store.path)) as db:
            self.assertIsNone(db.execute("SELECT 1 FROM sqlite_master WHERE name='scheduled_settings'").fetchone())

    def test_authenticated_schedule_roundtrip_without_sending(self):
        token = self.subscription["token"]
        payload = {"mode": "subject_prep", "time": "07:30", "subject": "체육"}
        with patch.dict(os.environ, {"OPENCIGAN_SCHEDULER_ENABLED": "1"}):
            self.assertEqual(self.request("GET", token="bad")[0], 401)
            self.assertEqual(json.loads(self.request("GET", token=token)[2]), {"schedule": None})
            self.assertEqual(self.request("PUT", {**payload, "time": "27:00"}, token)[0], 400)
            self.assertEqual(json.loads(self.request("PUT", payload, token)[2]), {"schedule": payload})
            self.assertEqual(json.loads(self.request("GET", token=token)[2]), {"schedule": payload})
            self.assertEqual(json.loads(self.request("DELETE", token=token)[2]), {"deleted": True})
            self.assertEqual(json.loads(self.request("GET", token=token)[2]), {"schedule": None})
            self.assertEqual(self.request("POST", token=token)[0], 405)
        self.assertEqual(self.store.deliveries(self.subscription["id"], token), [])


if __name__ == "__main__":
    unittest.main()
