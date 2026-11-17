"""Authentication boundary tests for Cloudflare visitor IP attribution."""

import hashlib
import hmac
import os
import time
import unittest
from unittest.mock import patch

from backend.app import resolve_client_ip
from backend.signed_client_ip import verify_signed_client_ip

KEY = "long-shared-key-for-testing-only-0123456789abcdef"


def signed_environ(ip="203.0.113.9", *, when=None):
    timestamp = str(int(time.time() if when is None else when))
    method, path, query = "GET", "/api/v1/timetable", "school=2%3AExample&grade=2"
    payload = "\n".join((method, path, query, ip, timestamp)).encode("utf-8")
    signature = hmac.new(KEY.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    return {
        "REMOTE_ADDR": "127.0.0.1",
        "REQUEST_METHOD": method, "PATH_INFO": path, "QUERY_STRING": query,
        "HTTP_X_FORWARDED_FOR": "198.51.100.77",
        "HTTP_X_OPENCIGAN_CLIENT_IP": ip,
        "HTTP_X_OPENCIGAN_IP_TIMESTAMP": timestamp,
        "HTTP_X_OPENCIGAN_IP_SIGNATURE": signature,
    }


class SignedClientIPTests(unittest.TestCase):
    def test_valid_signature_overrides_loopback_proxy(self):
        with patch.dict(os.environ, {"OPENCIGAN_PROXY_IP_SIGNING_KEY": KEY, "OPENCIGAN_TRUSTED_PROXIES": "127.0.0.1/32"}):
            self.assertEqual(resolve_client_ip(signed_environ()), "203.0.113.9")

    def test_spoofed_unsigned_modified_claim_falls_back_to_peer(self):
        with patch.dict(os.environ, {"OPENCIGAN_PROXY_IP_SIGNING_KEY": KEY, "OPENCIGAN_TRUSTED_PROXIES": "127.0.0.1/32"}):
            changes = [
                {"HTTP_X_OPENCIGAN_IP_SIGNATURE": ""},
                {"HTTP_X_OPENCIGAN_CLIENT_IP": "192.0.2.40"},
                {"QUERY_STRING": "school=2%3AOther&grade=2"},
                {"PATH_INFO": "/api/v1/status"},
                {"REQUEST_METHOD": "POST"},
                {"HTTP_X_OPENCIGAN_CLIENT_IP": "not-an-ip"},
            ]
            for change in changes:
                with self.subTest(change=change):
                    req = signed_environ()
                    req.update(change)
                    self.assertEqual(resolve_client_ip(req), "127.0.0.1")
            self.assertEqual(resolve_client_ip({"REMOTE_ADDR": "127.0.0.1", "HTTP_X_FORWARDED_FOR": "1.2.3.4"}), "127.0.0.1")

    def test_expired_bad_key_and_ipv6(self):
        self.assertIsNone(verify_signed_client_ip(signed_environ(when=time.time()-100), KEY))
        self.assertIsNone(verify_signed_client_ip(signed_environ(), KEY + "wrong"))
        self.assertIsNone(verify_signed_client_ip(signed_environ(), "short"))
        self.assertEqual(verify_signed_client_ip(signed_environ("2001:db8::a"), KEY), "2001:db8::a")

    def test_legacy_proxy_behavior_if_not_configured(self):
        with patch.dict(os.environ, {"OPENCIGAN_PROXY_IP_SIGNING_KEY": "", "OPENCIGAN_TRUSTED_PROXIES": "127.0.0.1/32"}):
            self.assertEqual(resolve_client_ip(signed_environ()), "198.51.100.77")


if __name__ == "__main__":
    unittest.main()
