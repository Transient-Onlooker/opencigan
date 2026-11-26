import hashlib
import hmac
import unittest
from unittest.mock import Mock, patch
from datetime import datetime, timezone

import requests

from backend.webhook_delivery import send_webhook, signature, validate_destination


class WebhookDeliveryTests(unittest.TestCase):
    def test_retry_after_http_date_is_bounded(self):
        now = datetime(2026, 11, 26, 12, 0, tzinfo=timezone.utc)
        for value, expected in (("Thu, 26 Nov 2026 12:01:30 GMT", 90),
                                ("Thu, 26 Nov 2026 14:00:00 GMT", 3600),
                                ("Thu, 26 Nov 2026 11:59:00 GMT", 0),
                                ("invalid", None)):
            with self.subTest(value=value), patch('backend.webhook_delivery.datetime') as clock:
                clock.now.return_value = now
                response = Mock(status_code=429, headers={"Retry-After": value})
                session = Mock()
                session.post.return_value = response
                context = Mock()
                context.__enter__ = Mock(return_value=session)
                context.__exit__ = Mock(return_value=False)
                result = send_webhook("https://discord.com/api/webhooks/123/token", b"{}", b"x" * 32, "id", lambda: context)
                self.assertEqual(result["retryAfter"], expected)
                response.close.assert_called_once()

    def test_destination_allowlist_rejects_tricks_and_redacts_secrets(self):
        self.assertEqual(validate_destination("https://discord.com/api/webhooks/123/token_ABC"), "discord")
        self.assertEqual(validate_destination("https://chat.googleapis.com/v1/spaces/abc/messages?key=K&token=T"), "google-chat")
        for url in ("http://discord.com/api/webhooks/123/token", "https://discord.com.evil.test/api/webhooks/123/token",
                    "https://discord.com@127.0.0.1/api/webhooks/123/token", "https://discord.com:444/api/webhooks/123/token",
                    "https://discord.com/api/webhooks/123/token?secret=exposed", "https://chat.googleapis.com/v1/spaces/a/messages?secret=exposed",
                    "https://chat.googleapis.com/v1/spaces/a/messages?secret=exposed&token=T&key=K"):
            with self.subTest(url=url), self.assertRaises(ValueError) as error:
                validate_destination(url)
            self.assertNotIn("exposed", str(error.exception))

    def test_signed_delivery_and_retry_classification(self):
        secret, body = b"x" * 32, b'{"example":1}'
        self.assertEqual(signature(secret, body), "sha256=" + hmac.new(secret, body, hashlib.sha256).hexdigest())
        for status, retryable in ((204, False), (301, False), (400, False), (408, True), (429, True), (503, True)):
            response = Mock(status_code=status, headers={"Retry-After": "99999"})
            session = Mock()
            session.post.return_value = response
            context = Mock()
            context.__enter__ = Mock(return_value=session)
            context.__exit__ = Mock(return_value=False)
            result = send_webhook("https://discord.com/api/webhooks/123/token", body, secret, "event_1", lambda: context)
            self.assertEqual(result["delivered"], status == 204)
            self.assertEqual(result["retryable"], retryable)
            self.assertEqual(result["retryAfter"], 3600)
            self.assertFalse(session.trust_env)
            self.assertFalse(session.post.call_args.kwargs["allow_redirects"])
            self.assertEqual(session.post.call_args.kwargs["headers"]["X-OpenCigan-Signature"], signature(secret, body))
            response.close.assert_called_once()

    def test_network_failure_is_sanitized_and_retryable(self):
        session = Mock()
        session.post.side_effect = requests.ConnectionError("secret URL or other sensitive details")
        context = Mock()
        context.__enter__ = Mock(return_value=session)
        context.__exit__ = Mock(return_value=False)
        result = send_webhook("https://discord.com/api/webhooks/123/token", b"{}", b"x" * 32, "id", lambda: context)
        self.assertEqual(result, {"delivered": False, "retryable": True, "status": None, "retryAfter": None})

    def test_retry_after_fractional_seconds_are_rounded_up_and_bounded(self):
        for value, expected in (("1.5", 2), ("60.01", 61), ("0.1", 1), ("99999.0", 3600),
                                ("-1", None), ("nan", None), ("1e3", None), ("１", None), ("1.1234567", None)):
            with self.subTest(value=value):
                response = Mock(status_code=429, headers={"Retry-After": value})
                session = Mock()
                session.post.return_value = response
                context = Mock()
                context.__enter__ = Mock(return_value=session)
                context.__exit__ = Mock(return_value=False)
                result = send_webhook("https://discord.com/api/webhooks/123/token", b"{}", b"x" * 32, "id", lambda: context)
                self.assertEqual(result["retryAfter"], expected)
                response.close.assert_called_once()
