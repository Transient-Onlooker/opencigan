import io
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from backend.app import _rate_clients, dispatch_request, make_app
from backend.history import HistoryStore
from backend.webhook_store import WebhookStore
from backend.webhook_worker import deliver_next


class WebhookApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = str(Path(self.temp.name) / "history.sqlite")
        HistoryStore(self.path)
        self.payload = {"school": "2:예시학교", "grade": 2, "class": 3,
                        "destination": "https://discord.com/api/webhooks/123/secret"}
        _rate_clients.clear()

    def request(self, method, path, payload=None, token=None):
        body = json.dumps(payload, ensure_ascii=False).encode() if payload is not None else None
        headers = {"Authorization": "Bearer " + token} if token else {}
        return dispatch_request(method, path, "", request_body=body, request_headers=headers)

    def test_disabled_by_default_and_requires_existing_history(self):
        with patch.dict("os.environ", {"OPENCIGAN_HISTORY_DB": self.path, "OPENCIGAN_WEBHOOKS_ENABLED": ""}):
            self.assertEqual(self.request("POST", "/api/v1/webhooks", self.payload)[0], 503)
        with patch.dict("os.environ", {"OPENCIGAN_HISTORY_DB": self.path + "missing", "OPENCIGAN_WEBHOOKS_ENABLED": "1"}):
            self.assertEqual(self.request("POST", "/api/v1/webhooks", self.payload)[0], 503)
            self.assertFalse(Path(self.path + "missing").exists())

    def test_create_authenticate_and_delete_without_exposing_destination(self):
        with patch.dict("os.environ", {"OPENCIGAN_HISTORY_DB": self.path, "OPENCIGAN_WEBHOOKS_ENABLED": "1"}):
            status, headers, body = self.request("POST", "/api/v1/webhooks", self.payload)
            self.assertEqual(status, 200)
            self.assertEqual(headers["Cache-Control"], "no-store")
            self.assertNotIn(b"secret", body)
            created = json.loads(body)
            path = "/api/v1/webhooks/" + created["id"]
            for token in (None, "wrong"):
                self.assertEqual(self.request("GET", path, token=token)[0], 401)
                self.assertEqual(self.request("DELETE", path, token=token)[0], 401)
            status, _, body = self.request("GET", path, token=created["token"])
            self.assertEqual(status, 200)
            self.assertNotIn(b"secret", body)
            self.assertNotIn(created["token"].encode(), body)
            self.assertEqual(self.request("DELETE", path, token=created["token"])[0], 200)
            self.assertEqual(self.request("GET", path, token=created["token"])[0], 401)

    def test_rejects_invalid_destinations_and_large_input(self):
        with patch.dict("os.environ", {"OPENCIGAN_HISTORY_DB": self.path, "OPENCIGAN_WEBHOOKS_ENABLED": "1"}):
            for destination in ("https://127.0.0.1/", "https://discord.com.evil.test/api/webhooks/1/token"):
                status, _, body = self.request("POST", "/api/v1/webhooks", {**self.payload, "destination": destination})
                self.assertEqual(status, 400)
                self.assertNotIn(destination.encode(), body)
            self.assertEqual(dispatch_request("POST", "/api/v1/webhooks", "", request_body=b" " * 4097)[0], 413)
            self.assertEqual(dispatch_request("POST", "/api/v1/webhooks", "", request_body=b"[" * 1500 + b"]" * 1500)[0], 400)
            self.assertEqual(self.request("POST", "/api/v1/webhooks", {**self.payload, "school": "2:bad\nname"})[0], 400)

    def test_subscription_requests_have_their_own_rate_limit(self):
        with patch.dict("os.environ", {"OPENCIGAN_HISTORY_DB": self.path, "OPENCIGAN_WEBHOOKS_ENABLED": "1"}):
            for _ in range(60):
                self.assertEqual(dispatch_request("GET", "/api/v1/webhooks/" + "a" * 24, "", client="test-ip")[0], 401)
            status, headers, _ = dispatch_request("GET", "/api/v1/webhooks/" + "a" * 24, "", client="test-ip")
            self.assertEqual(status, 429)
            self.assertGreater(int(headers["Retry-After"]), 0)
            self.assertEqual(dispatch_request("GET", "/api/v1/status", "", client="test-ip")[0], 200)

    def test_wsgi_forwards_creation_body_and_auth_header(self):
        payload = json.dumps(self.payload).encode()
        environ = {"REQUEST_METHOD": "POST", "PATH_INFO": "/api/v1/webhooks", "QUERY_STRING": "",
                   "REMOTE_ADDR": "127.0.0.1", "CONTENT_LENGTH": str(len(payload)), "wsgi.input": io.BytesIO(payload)}
        statuses = []
        with patch.dict("os.environ", {"OPENCIGAN_HISTORY_DB": self.path, "OPENCIGAN_WEBHOOKS_ENABLED": "1"}):
            body = b"".join(make_app()(environ, lambda status, headers: statuses.append(status)))
            self.assertEqual(statuses.pop(), "200 OK")
            created = json.loads(body)
            environ.update({"REQUEST_METHOD": "GET", "PATH_INFO": "/api/v1/webhooks/" + created["id"],
                            "HTTP_AUTHORIZATION": "Bearer " + created["token"], "CONTENT_LENGTH": "0"})
            b"".join(make_app()(environ, lambda status, headers: statuses.append(status)))
            self.assertEqual(statuses.pop(), "200 OK")
            update = b'{"filters":{"period":1}}'
            environ.update({"REQUEST_METHOD": "PUT", "CONTENT_LENGTH": str(len(update)), "wsgi.input": io.BytesIO(update)})
            b"".join(make_app()(environ, lambda status, headers: statuses.append(status)))
            self.assertEqual(statuses.pop(), "200 OK")

    def test_api_subscription_receives_observed_change_in_mock_worker(self):
        with patch.dict("os.environ", {"OPENCIGAN_HISTORY_DB": self.path, "OPENCIGAN_WEBHOOKS_ENABLED": "1"}):
            status, _, _ = self.request("POST", "/api/v1/webhooks", self.payload)
            self.assertEqual(status, 200)
            history = HistoryStore(self.path)
            now = datetime.now(timezone.utc)
            lesson = {"grade": 2, "class": 3, "date": "2026-11-16", "period": 1, "subject": "수학", "teacher": "김"}
            history.observe(self.payload["school"], "2026-11-16", [lesson], now)
            history.observe(self.payload["school"], "2026-11-16", [{**lesson, "subject": "과학"}], now + timedelta(seconds=1))
            sent = []
            def sender(url, body, secret, event_id):
                sent.append((url, json.loads(body), event_id))
                return {"delivered": True, "retryable": False, "status": 204, "retryAfter": None}
            self.assertTrue(deliver_next(WebhookStore(self.path), now=now.timestamp() + 10, sender=sender))
            self.assertIn("과학", sent[0][1]["content"])
            self.assertTrue(sent[0][2].startswith("change_"))

    def test_delivery_history_requires_token_and_omits_secrets_and_payload(self):
        with patch.dict("os.environ", {"OPENCIGAN_HISTORY_DB": self.path, "OPENCIGAN_WEBHOOKS_ENABLED": "1"}):
            _, _, body = self.request("POST", "/api/v1/webhooks", self.payload)
            created = json.loads(body)
            store = WebhookStore(self.path)
            store.enqueue(created["id"], "event_1", b'{"text":"private lesson"}', now=10)
            item = store.claim(now=10)
            store.finish(item["id"], item["leaseToken"], {"delivered": False, "retryable": False, "status": 400}, now=11)
            path = "/api/v1/webhooks/" + created["id"] + "/deliveries"
            self.assertEqual(self.request("GET", path, token="wrong")[0], 401)
            status, headers, body = self.request("GET", path, token=created["token"])
            self.assertEqual((status, headers["Cache-Control"]), (200, "no-store"))
            self.assertEqual(json.loads(body)["deliveries"][0]["state"], "failed")
            for value in (b"private lesson", b"secret", created["token"].encode()):
                self.assertNotIn(value, body)
            self.assertEqual(self.request("DELETE", path, token=created["token"])[0], 405)

    def test_test_notification_is_authenticated_rate_limited_and_delivered_by_worker(self):
        with patch.dict("os.environ", {"OPENCIGAN_HISTORY_DB": self.path, "OPENCIGAN_WEBHOOKS_ENABLED": "1"}):
            _, _, body = self.request("POST", "/api/v1/webhooks", self.payload)
            created = json.loads(body)
            path = "/api/v1/webhooks/" + created["id"] + "/test"
            self.assertEqual(self.request("POST", path, token="wrong")[0], 401)
            status, _, body = self.request("POST", path, token=created["token"])
            self.assertEqual(status, 200)
            event_id = json.loads(body)["eventId"]
            self.assertTrue(event_id.startswith("test_"))
            self.assertEqual(self.request("POST", path, token=created["token"])[0], 429)
            sent = []
            def sender(url, body, secret, event):
                sent.append((json.loads(body), event))
                return {"delivered": True, "retryable": False, "status": 204, "retryAfter": None}
            self.assertTrue(deliver_next(WebhookStore(self.path), sender=sender))
            self.assertEqual(sent[0][1], event_id)
            self.assertIn("테스트 알림", sent[0][0]["content"])
            self.assertEqual(self.request("POST", path, token=created["token"])[0], 429)

    def test_filter_update_requires_token_and_applies_to_future_changes(self):
        with patch.dict("os.environ", {"OPENCIGAN_HISTORY_DB": self.path, "OPENCIGAN_WEBHOOKS_ENABLED": "1"}):
            _, _, body = self.request("POST", "/api/v1/webhooks", self.payload)
            created = json.loads(body)
            path = "/api/v1/webhooks/" + created["id"]
            filters = {"subject": "수학", "teacher": "이", "weekday": 1, "period": 1, "type": "changed"}
            self.assertEqual(self.request("PUT", path, {"filters": filters}, "wrong")[0], 401)
            self.assertEqual(self.request("PUT", path, {"filters": {"period": True}}, created["token"])[0], 400)
            self.assertEqual(self.request("PUT", path, {"filters": filters}, created["token"])[0], 200)
            self.assertEqual(json.loads(self.request("GET", path, token=created["token"])[2])["filters"], filters)
            history = HistoryStore(self.path)
            now = datetime.now(timezone.utc)
            lesson = {"grade": 2, "class": 3, "date": "2026-11-16", "period": 1, "subject": "수학", "teacher": "김"}
            history.observe(self.payload["school"], "2026-11-16", [lesson], now)
            history.observe(self.payload["school"], "2026-11-16", [{**lesson, "subject": "과학", "teacher": "이"}], now + timedelta(seconds=1))
            self.assertEqual(len(WebhookStore(self.path).deliveries(created["id"], created["token"])), 1)
            history.observe(self.payload["school"], "2026-11-16", [{**lesson, "subject": "영어", "teacher": "박"}], now + timedelta(seconds=2))
            self.assertEqual(len(WebhookStore(self.path).deliveries(created["id"], created["token"])), 1)

    def test_rotate_management_token_via_api(self):
        with patch.dict("os.environ", {"OPENCIGAN_HISTORY_DB": self.path, "OPENCIGAN_WEBHOOKS_ENABLED": "1"}):
            _, _, body = self.request("POST", "/api/v1/webhooks", self.payload)
            created1 = json.loads(body)
            id1, old_token1 = created1["id"], created1["token"]

            # Create second subscription to verify it remains unaffected
            payload2 = {**self.payload, "class": 4}
            _, _, body2 = self.request("POST", "/api/v1/webhooks", payload2)
            created2 = json.loads(body2)
            id2, token2 = created2["id"], created2["token"]

            path1 = f"/api/v1/webhooks/{id1}/rotate"
            new_token1 = 'b' * 43
            rotation = {"newToken": new_token1}

            # Non-POST methods rejected
            for method in ("GET", "PUT", "DELETE"):
                self.assertEqual(self.request(method, path1, token=old_token1)[0], 405)

            # Unauthorized requests rejected
            self.assertEqual(self.request("POST", path1, payload=rotation, token=None)[0], 401)
            self.assertEqual(self.request("POST", path1, payload=rotation, token="invalid_token_value_not_matching_hex_or_hash")[0], 401)

            # Reject non-empty payload
            self.assertEqual(self.request("POST", path1, payload={"extra": 1}, token=old_token1)[0], 400)

            # Successful rotation
            status, headers, rotate_body = self.request("POST", path1, payload=rotation, token=old_token1)
            self.assertEqual(status, 200)
            self.assertEqual(headers["Cache-Control"], "no-store")
            rotated = json.loads(rotate_body)
            self.assertEqual(rotated, {"rotated": True})
            self.assertNotEqual(old_token1, new_token1)
            self.assertNotIn(old_token1.encode(), rotate_body)
            self.assertNotIn(new_token1.encode(), rotate_body)

            # Even if the response is lost, the caller already knows the new token.
            self.assertEqual(self.request("GET", f"/api/v1/webhooks/{id1}", token=new_token1)[0], 200)

            # Old token immediately rejected across all endpoints
            self.assertEqual(self.request("GET", f"/api/v1/webhooks/{id1}", token=old_token1)[0], 401)
            self.assertEqual(self.request("POST", path1, payload={"newToken": 'c' * 43}, token=old_token1)[0], 401)
            self.assertEqual(self.request("DELETE", f"/api/v1/webhooks/{id1}", token=old_token1)[0], 401)

            # New token accepted
            status_get, _, body_get = self.request("GET", f"/api/v1/webhooks/{id1}", token=new_token1)
            self.assertEqual(status_get, 200)
            self.assertEqual(json.loads(body_get)["classroom"], 3)

            # Second subscription completely unaffected
            status2, _, body2_check = self.request("GET", f"/api/v1/webhooks/{id2}", token=token2)
            self.assertEqual(status2, 200)
            self.assertEqual(json.loads(body2_check)["classroom"], 4)

    def test_rotation_wsgi_forwards_candidate_and_auth(self):
        with patch.dict("os.environ", {"OPENCIGAN_HISTORY_DB": self.path, "OPENCIGAN_WEBHOOKS_ENABLED": "1"}):
            _, _, body = self.request("POST", "/api/v1/webhooks", self.payload)
            created = json.loads(body)
            payload = json.dumps({"newToken": "c" * 43}).encode()
            environ = {"REQUEST_METHOD": "POST", "PATH_INFO": f"/api/v1/webhooks/{created['id']}/rotate",
                       "QUERY_STRING": "", "REMOTE_ADDR": "127.0.0.1", "CONTENT_LENGTH": str(len(payload)),
                       "HTTP_AUTHORIZATION": "Bearer " + created['token'], "wsgi.input": io.BytesIO(payload)}
            statuses = []
            result = b''.join(make_app()(environ, lambda status, headers: statuses.append(status)))
            self.assertEqual(statuses, ['200 OK'])
            self.assertEqual(json.loads(result), {"rotated": True})
            self.assertEqual(self.request("GET", f"/api/v1/webhooks/{created['id']}", token="c" * 43)[0], 200)
