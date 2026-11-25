import json
import unittest
from unittest.mock import Mock

from backend.admin_alert_delivery import send_admin_alert


class AdminAlertDeliveryTests(unittest.TestCase):
    def test_minimal_payload_and_stable_event_id(self):
        send = Mock(return_value={"delivered": True})
        url = "https://discord.com/api/webhooks/123/test_secret"
        result = send_admin_alert(url, b"x" * 32, "evt_123", "status_errors", "429", send=send)
        self.assertTrue(result["delivered"])
        destination, body, secret, event_id = send.call_args.args
        self.assertEqual((destination, secret, event_id), (url, b"x" * 32, "evt_123"))
        payload = json.loads(body)
        self.assertEqual(payload["allowed_mentions"], {"parse": []})
        self.assertIn("429", payload["content"])
        self.assertNotIn("test_secret", payload["content"])

    def test_invalid_destination_and_kind_do_not_send(self):
        send = Mock()
        for url, kind, group in (("http://127.0.0.1/", "status_errors", "429"),
                                 ("https://discord.com/api/webhooks/123/token", "unknown", None),
                                 ("https://discord.com/api/webhooks/123/token", "status_errors", "200")):
            with self.subTest(url=url, kind=kind, group=group), self.assertRaises(ValueError):
                send_admin_alert(url, b"x" * 32, "evt_1", kind, group, send=send)
        send.assert_not_called()


if __name__ == "__main__":
    unittest.main()
