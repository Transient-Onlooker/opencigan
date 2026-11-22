import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import yaml
from jsonschema import Draft202012Validator

from backend.app import dispatch_request
from backend.scheduled_store import ScheduledStore
from backend.webhook_store import WebhookStore


class ScheduledContractTests(unittest.TestCase):
    def test_canceled_delivery_matches_openapi(self):
        spec = yaml.safe_load((Path(__file__).resolve().parents[1] / "docs" / "openapi.yaml").read_text(encoding="utf-8"))
        root = Path.home() / "AppData" / "Local" / "Temp" if os.name == "nt" else None
        with tempfile.TemporaryDirectory(dir=root) as directory:
            db = Path(directory) / "history.sqlite"
            store = WebhookStore(db)
            sub = store.create("2:Example", 2, 3, "https://discord.com/api/webhooks/123/secret")
            schedules = ScheduledStore(db)
            setting = schedules.set_schedule(sub["id"], sub["token"], "daily_summary", "07:30")
            self.assertTrue(schedules.enqueue_due(sub["id"], setting["revision"], "2026-11-23", b"{}", 100))
            self.assertIsNotNone(store.claim(now=100))
            self.assertTrue(schedules.cancel_schedule(sub["id"], sub["token"]))
            path = f"/api/v1/webhooks/{sub['id']}/deliveries"
            headers = {"Authorization": f"Bearer {sub['token']}"}
            with patch("backend.app._webhook_store", return_value=store):
                status, _, response = dispatch_request("GET", path, "", request_headers=headers,
                                                       shutter_instance=Mock(check=Mock(return_value=(True, 0))))
            self.assertEqual(status, 200)
            result = json.loads(response)
            self.assertEqual(result["deliveries"][0]["state"], "canceled")
            schema = spec["paths"]["/api/v1/webhooks/{id}/deliveries"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
            Draft202012Validator(schema).validate(result)

    def test_schedule_api_matches_openapi_and_rejects_invalid_subject(self):
        spec = yaml.safe_load((Path(__file__).resolve().parents[1] / "docs" / "openapi.yaml").read_text(encoding="utf-8"))
        path_template = "/api/v1/webhooks/{id}/schedule"
        root = Path.home() / "AppData" / "Local" / "Temp" if os.name == "nt" else None
        with tempfile.TemporaryDirectory(dir=root) as directory:
            store = WebhookStore(Path(directory) / "history.sqlite")
            sub = store.create("2:Example", 2, 3, "https://discord.com/api/webhooks/123/secret")
            path = f"/api/v1/webhooks/{sub['id']}/schedule"
            headers = {"Authorization": f"Bearer {sub['token']}"}
            payload = {"mode": "subject_prep", "time": "07:30", "subject": "체육"}
            request_schema = spec["paths"][path_template]["put"]["requestBody"]["content"]["application/json"]["schema"]
            Draft202012Validator(request_schema).validate(payload)
            self.assertFalse(Draft202012Validator(request_schema).is_valid({**payload, "subject": None}))
            self.assertFalse(Draft202012Validator(request_schema).is_valid({**payload, "subject": "   "}))
            with patch("backend.app._webhook_store", return_value=store), patch.dict(os.environ, {"OPENCIGAN_SCHEDULER_ENABLED": "1"}):
                for method, request in (("GET", None), ("PUT", payload), ("GET", None), ("DELETE", None)):
                    body = json.dumps(request).encode() if request is not None else None
                    status, _, response = dispatch_request(method, path, "", request_body=body, request_headers=headers,
                                                           shutter_instance=Mock(check=Mock(return_value=(True, 0))))
                    self.assertEqual(status, 200)
                    schema = spec["paths"][path_template][method.lower()]["responses"]["200"]["content"]["application/json"]["schema"]
                    Draft202012Validator(schema).validate(json.loads(response))


if __name__ == "__main__":
    unittest.main()
