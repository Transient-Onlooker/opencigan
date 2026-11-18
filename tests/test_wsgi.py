import io
import hashlib
import hmac
import json
import os
import threading
import time
import unittest
from http.client import HTTPConnection
from unittest.mock import Mock, patch

from backend.app import Handler, SafeWSGIRequestHandler, ThreadingWSGIServer, make_app, serve, _rate_clients, _waitress_proxy_kwargs, resolve_client_ip
from backend.cache import Cache


class WsGITests(unittest.TestCase):
    def setUp(self):
        _rate_clients.clear()
        self.cache = Cache()
        self.app = make_app(cache_instance=self.cache)

    def _call_app(self, method, path, query_string="", headers=None, body=b"", remote_addr=None, app=None):
        environ = {
            "REQUEST_METHOD": method,
            "PATH_INFO": path,
            "QUERY_STRING": query_string,
            "SERVER_NAME": "localhost",
            "SERVER_PORT": "80",
            "wsgi.version": (1, 0),
            "wsgi.url_scheme": "http",
            "wsgi.input": io.BytesIO(body),
            "wsgi.errors": io.StringIO(),
            "wsgi.multithread": True,
            "wsgi.multiprocess": False,
            "wsgi.run_once": False,
        }
        if remote_addr is not None:
            environ["REMOTE_ADDR"] = remote_addr
        if headers:
            for k, v in headers.items():
                environ["HTTP_" + k.upper().replace("-", "_")] = v

        captured = {}

        def start_response(status, response_headers, exc_info=None):
            captured["status"] = status
            captured["headers"] = dict(response_headers)

        target_app = app if app is not None else self.app
        response_iter = target_app(environ, start_response)
        response_body = b"".join(response_iter)
        return captured.get("status"), captured.get("headers"), response_body

    def test_status_endpoint_via_wsgi(self):
        status, headers, body = self._call_app("GET", "/api/v1/status")
        self.assertEqual(status, "200 OK")
        self.assertEqual(headers["Content-Type"], "application/json; charset=utf-8")
        data = json.loads(body.decode("utf-8"))
        self.assertEqual(data, {"status": "ok", "scope": "process liveness"})

    def test_cors_options_preflight(self):
        with patch.dict(os.environ, {"ALLOWED_ORIGIN": "https://transient-onlooker.github.io"}):
            status, headers, body = self._call_app("OPTIONS", "/api/v1/schools", "q=test")
            self.assertEqual(status, "204 No Content")
            self.assertEqual(headers["Access-Control-Allow-Origin"], "https://transient-onlooker.github.io")
            self.assertIn("OPTIONS", headers["Access-Control-Allow-Methods"])
            self.assertEqual(body, b"")

    def test_head_method_returns_headers_with_empty_body(self):
        status, headers, body = self._call_app("HEAD", "/api/v1/status")
        self.assertEqual(status, "200 OK")
        self.assertEqual(headers["Content-Type"], "application/json; charset=utf-8")
        self.assertEqual(body, b"")

    def test_method_not_allowed(self):
        for method in ("POST", "PUT", "DELETE", "PATCH"):
            status, headers, body = self._call_app(method, "/api/v1/status")
            self.assertEqual(status, "405 Method Not Allowed")
            data = json.loads(body.decode("utf-8"))
            self.assertIn("error", data)

    def test_not_found(self):
        status, headers, body = self._call_app("GET", "/api/v1/unknown")
        self.assertEqual(status, "404 Not Found")
        data = json.loads(body.decode("utf-8"))
        self.assertEqual(data["error"], "요청한 경로가 없습니다")

    def test_invalid_query_parameter(self):
        status, headers, body = self._call_app("GET", "/api/v1/schools", "q=")
        self.assertEqual(status, "400 Bad Request")
        data = json.loads(body.decode("utf-8"))
        self.assertIn("error", data)

    def test_default_ignores_forwarded_headers_and_uses_remote_addr(self):
        with patch.dict(os.environ, {"OPENCIGAN_TRUSTED_PROXIES": "", "TRUSTED_PROXIES": ""}):
            app = make_app(cache_instance=self.cache)
            for _ in range(60):
                status, _, _ = self._call_app(
                    "GET", "/api/v1/unknown", "",
                    headers={"X-Forwarded-For": "203.0.113.195"},
                    remote_addr="127.0.0.1", app=app,
                )
                self.assertEqual(status, "404 Not Found")
            # 61st request from same REMOTE_ADDR is rate limited even with different XFF
            status, headers, body = self._call_app(
                "GET", "/api/v1/unknown", "",
                headers={"X-Forwarded-For": "198.51.100.77"},
                remote_addr="127.0.0.1", app=app,
            )
            self.assertEqual(status, "429 Too Many Requests")
            self.assertEqual(json.loads(body.decode("utf-8"))["code"], "rate_limited")

    @patch.dict(os.environ, {"OPENCIGAN_PROXY_IP_SIGNING_KEY": "s" * 32, "OPENCIGAN_ACCESS_LOG_DB": "fixture"})
    @patch("backend.app._access_log_recorder")
    @patch("backend.app.shutter.check", return_value=(True, 0))
    def test_signed_and_unsigned_requests_have_separate_limits(self, _shutter, recorder):
        timestamp = str(int(time.time()))
        message = "\n".join(("GET", "/api/v1/unknown", "", "203.0.113.9", timestamp))
        signature = hmac.new(b"s" * 32, message.encode(), hashlib.sha256).hexdigest()
        signed = {"X-Opencigan-Client-IP": "203.0.113.9", "X-Opencigan-IP-Timestamp": timestamp,
                  "X-Opencigan-IP-Signature": signature}
        for _ in range(60):
            self.assertEqual(self._call_app("GET", "/api/v1/unknown", remote_addr="127.0.0.1")[0], "404 Not Found")
        self.assertEqual(self._call_app("GET", "/api/v1/unknown", remote_addr="127.0.0.1")[0], "429 Too Many Requests")
        self.assertEqual(self._call_app("GET", "/api/v1/unknown", remote_addr="127.0.0.1", headers=signed)[0], "404 Not Found")
        self.assertEqual(recorder.submit.call_args.args[0]["client_ip"], "203.0.113.9")
        forged = {**signed, "X-Opencigan-IP-Signature": "0" * 64}
        self.assertEqual(self._call_app("GET", "/api/v1/unknown", remote_addr="127.0.0.1", headers=forged)[0], "429 Too Many Requests")
        self.assertEqual(self._call_app("OPTIONS", "/api/v1/unknown", remote_addr="127.0.0.1")[0], "204 No Content")
        for _ in range(59):
            self.assertEqual(self._call_app("GET", "/api/v1/unknown", remote_addr="127.0.0.1", headers=signed)[0], "404 Not Found")
        self.assertEqual(self._call_app("GET", "/api/v1/unknown", remote_addr="127.0.0.1", headers=signed)[0], "429 Too Many Requests")

    @patch.dict(os.environ, {"OPENCIGAN_ANALYTICS_ADMIN_TOKEN": "test-token",
                            "OPENCIGAN_ACCESS_LOG_ADMIN_TOKEN": "test-token",
                            "OPENCIGAN_PROXY_IP_SIGNING_KEY": ""})
    @patch("backend.app.shutter.check", return_value=(True, 0))
    def test_admin_auth_attempts_are_rate_limited_separately_per_client(self, _shutter):
        paths = ("/api/v1/admin/analytics", "/api/v1/admin/access-logs")
        for i in range(60):
            status, _, _ = self._call_app("GET", paths[i % 2], remote_addr="203.0.113.9")
            self.assertEqual(status, "401 Unauthorized")
        status, headers, body = self._call_app("GET", paths[0], remote_addr="203.0.113.9")
        self.assertEqual(status, "429 Too Many Requests")
        self.assertGreater(int(headers["Retry-After"]), 0)
        self.assertEqual(json.loads(body)["code"], "rate_limited")
        self.assertEqual(self._call_app("GET", paths[1], remote_addr="203.0.113.10")[0], "401 Unauthorized")
        self.assertEqual(self._call_app("GET", "/api/v1/status", remote_addr="203.0.113.9")[0], "200 OK")
        self.assertEqual(self._call_app("GET", "/api/v1/unknown", remote_addr="203.0.113.9")[0], "404 Not Found")
        self.assertEqual(self._call_app("OPTIONS", paths[0], remote_addr="203.0.113.9")[0], "204 No Content")

    @patch.dict(os.environ, {"OPENCIGAN_ANALYTICS_ADMIN_TOKEN": "test-token",
                            "OPENCIGAN_PROXY_IP_SIGNING_KEY": "s" * 32})
    def test_admin_limit_keeps_verified_and_unsigned_clients_separate(self):
        path = "/api/v1/admin/analytics"
        timestamp = str(int(time.time()))
        payload = "\n".join(("GET", path, "", "203.0.113.9", timestamp))
        signature = hmac.new(b"s" * 32, payload.encode(), hashlib.sha256).hexdigest()
        signed = {"X-Opencigan-Client-IP": "203.0.113.9", "X-Opencigan-IP-Timestamp": timestamp,
                  "X-Opencigan-IP-Signature": signature}
        for _ in range(60):
            self.assertEqual(self._call_app("GET", path, remote_addr="127.0.0.1")[0], "401 Unauthorized")
        self.assertEqual(self._call_app("GET", path, remote_addr="127.0.0.1")[0], "429 Too Many Requests")
        self.assertEqual(self._call_app("GET", path, remote_addr="127.0.0.1", headers=signed)[0], "401 Unauthorized")
        forged = {**signed, "X-Opencigan-IP-Signature": "0" * 64}
        self.assertEqual(self._call_app("GET", path, remote_addr="127.0.0.1", headers=forged)[0], "429 Too Many Requests")

    @patch.dict(os.environ, {"OPENCIGAN_ACCESS_LOG_DB": "fixture"})
    @patch("backend.app._access_log_recorder")
    def test_opt_in_trusted_proxies_separates_clients_and_logs_same_identity(self, recorder: Mock):
        app = make_app(cache_instance=self.cache, trusted_proxies="127.0.0.1, 10.0.0.0/8")
        # Exhaust Client A rate limit through trusted proxy
        for _ in range(60):
            status, _, _ = self._call_app(
                "GET", "/api/v1/unknown", "",
                headers={"X-Forwarded-For": f"192.0.2.{_ + 1}, 203.0.113.1, 10.0.0.2"},
                remote_addr="127.0.0.1", app=app,
            )
            self.assertEqual(status, "404 Not Found")
        status, headers, body = self._call_app(
            "GET", "/api/v1/unknown", "",
            headers={"X-Forwarded-For": "203.0.113.1"},
            remote_addr="127.0.0.1", app=app,
        )
        self.assertEqual(status, "429 Too Many Requests")

        # Client B through same trusted proxy is NOT rate limited
        status_b, _, _ = self._call_app(
            "GET", "/api/v1/unknown", "",
            headers={"X-Forwarded-For": "203.0.113.2"},
            remote_addr="127.0.0.1", app=app,
        )
        self.assertEqual(status_b, "404 Not Found")
        events = [(call.args[0]["client_ip"], call.args[0]["status"]) for call in recorder.submit.call_args_list]
        self.assertEqual(events, [("203.0.113.1", 404)] * 60 + [("203.0.113.1", 429), ("203.0.113.2", 404)])

    def test_untrusted_immediate_peer_ignores_forwarded_headers(self):
        app = make_app(cache_instance=self.cache, trusted_proxies="127.0.0.1")
        # Untrusted remote_addr cannot spoof client IP
        for _ in range(60):
            self._call_app(
                "GET", "/api/v1/unknown", "",
                headers={"X-Forwarded-For": "203.0.113.10"},
                remote_addr="198.51.100.1", app=app,
            )
        status, _, body = self._call_app(
            "GET", "/api/v1/unknown", "",
            headers={"X-Forwarded-For": "203.0.113.99"},
            remote_addr="198.51.100.1", app=app,
        )
        self.assertEqual(status, "429 Too Many Requests")

    def test_multi_hop_trusted_proxy_and_spoof_prevention(self):
        environ = {
            "REMOTE_ADDR": "127.0.0.1",
            "HTTP_X_FORWARDED_FOR": "8.8.8.8, 203.0.113.50, 10.0.0.2",
        }
        # 127.0.0.1 is trusted; 10.0.0.2 is trusted; 203.0.113.50 is untrusted
        # 8.8.8.8 was spoofed by 203.0.113.50 and must be ignored
        client = resolve_client_ip(environ, trusted_proxies="127.0.0.1, 10.0.0.0/8")
        self.assertEqual(client, "203.0.113.50")

    def test_malformed_and_oversized_spoof_chains_fail_safe(self):
        trusted = "127.0.0.1, ::1"
        base_env = {"REMOTE_ADDR": "127.0.0.1"}

        # Malformed IP in chain
        env1 = {**base_env, "HTTP_X_FORWARDED_FOR": "not-an-ip, 127.0.0.1"}
        self.assertEqual(resolve_client_ip(env1, trusted), "127.0.0.1")

        # Empty hop in chain
        env2 = {**base_env, "HTTP_X_FORWARDED_FOR": "203.0.113.1, , 127.0.0.1"}
        self.assertEqual(resolve_client_ip(env2, trusted), "127.0.0.1")

        # Malformed entries must invalidate the entire chain even before an untrusted hop.
        env2b = {**base_env, "HTTP_X_FORWARDED_FOR": "not-an-ip, 203.0.113.1, 127.0.0.1"}
        self.assertEqual(resolve_client_ip(env2b, trusted), "127.0.0.1")
        env2c = {**base_env, "HTTP_FORWARDED": 'for=invalid, for="203.0.113.1", for=127.0.0.1'}
        self.assertEqual(resolve_client_ip(env2c, trusted), "127.0.0.1")

        # Oversized header (> 1024 chars)
        env3 = {**base_env, "HTTP_X_FORWARDED_FOR": "1.1.1.1, " * 150}
        self.assertEqual(resolve_client_ip(env3, trusted), "127.0.0.1")

        # Excessive hops (> 16 hops)
        env4 = {**base_env, "HTTP_X_FORWARDED_FOR": ", ".join(f"192.0.2.{i}" for i in range(25))}
        self.assertEqual(resolve_client_ip(env4, trusted), "127.0.0.1")

        # Conflicting headers (both XFF and Forwarded)
        env5 = {
            **base_env,
            "HTTP_X_FORWARDED_FOR": "203.0.113.1",
            "HTTP_FORWARDED": 'for="203.0.113.2"',
        }
        self.assertEqual(resolve_client_ip(env5, trusted), "127.0.0.1")

        # Ports and brackets cleaned safely
        env6 = {**base_env, "HTTP_X_FORWARDED_FOR": "203.0.113.5:8080"}
        self.assertEqual(resolve_client_ip(env6, trusted), "203.0.113.5")

        env7 = {"REMOTE_ADDR": "::1", "HTTP_X_FORWARDED_FOR": "[2001:db8::1]:443"}
        self.assertEqual(resolve_client_ip(env7, trusted), "2001:db8::1")

        # RFC 7239 Forwarded header parsed correctly
        env8 = {**base_env, "HTTP_FORWARDED": 'for="198.51.100.22:1234";proto=https'}
        self.assertEqual(resolve_client_ip(env8, trusted), "198.51.100.22")

    def test_live_threading_wsgi_server(self):
        import wsgiref.simple_server

        server = wsgiref.simple_server.make_server(
            "127.0.0.1", 0, self.app, server_class=ThreadingWSGIServer, handler_class=SafeWSGIRequestHandler
        )
        port = server.server_port
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            conn = HTTPConnection("127.0.0.1", port, timeout=5)
            with self.assertLogs("opensigan", level="INFO") as logs:
                conn.request("GET", "/api/v1/status?private-query=secret")
                res = conn.getresponse()
                self.assertEqual(res.status, 200)
                payload = json.loads(res.read().decode("utf-8"))
            self.assertEqual(payload["status"], "ok")
            self.assertNotIn("private-query", "\n".join(logs.output))
            conn.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_forwarded_rejects_ambiguous_or_malformed_addresses(self):
        for value in ['for=198.51.100.1;for=198.51.100.2', 'for="198.51.100.1',
                      'for=[2001:db8::1]junk', 'for=198.51.100.1:99999',
                      "for='198.51.100.1'", 'for=fe80::1%eth0']:
            with self.subTest(value=value):
                self.assertEqual(resolve_client_ip({
                    'REMOTE_ADDR': '127.0.0.1', 'HTTP_FORWARDED': value,
                }, '127.0.0.1'), '127.0.0.1')
        self.assertEqual(resolve_client_ip({
            'REMOTE_ADDR': '127.0.0.1', 'HTTP_FORWARDED': 'proto=https; for="198.51.100.1"',
        }, '127.0.0.1'), '198.51.100.1')

    def test_unrelated_environment_variable_cannot_enable_proxy_trust(self):
        with patch.dict(os.environ, {'OPENCIGAN_TRUSTED_PROXIES': '', 'TRUSTED_PROXIES': '127.0.0.1'}):
            self.assertEqual(resolve_client_ip({
                'REMOTE_ADDR': '127.0.0.1', 'HTTP_X_FORWARDED_FOR': '198.51.100.1',
            }), '127.0.0.1')

    def test_waitress_proxy_kwargs_empty_without_trusted_proxies(self):
        with patch.dict(os.environ, {'OPENCIGAN_TRUSTED_PROXIES': ''}):
            self.assertEqual(_waitress_proxy_kwargs(), {})

    def test_waitress_proxy_kwargs_mirror_loopback_proxy(self):
        with patch.dict(os.environ, {'OPENCIGAN_TRUSTED_PROXIES': '127.0.0.1/32, ::1/128'}):
            self.assertEqual(_waitress_proxy_kwargs(), {
                'trusted_proxy': '127.0.0.1',
                'trusted_proxy_count': 1,
                'trusted_proxy_headers': {'x-forwarded-for'},
            })


    def test_signed_mode_disables_waitress_forwarded_ip_rewrite(self):
        with patch.dict(os.environ, {
            "OPENCIGAN_TRUSTED_PROXIES": "127.0.0.1/32",
            "OPENCIGAN_PROXY_IP_SIGNING_KEY": "long-shared-key-for-testing-only-0123456789abcdef",
        }):
            self.assertEqual(_waitress_proxy_kwargs(), {})

    def test_waitress_proxy_kwargs_ignore_non_loopback(self):
        with patch.dict(os.environ, {'OPENCIGAN_TRUSTED_PROXIES': '10.0.0.0/8'}):
            self.assertEqual(_waitress_proxy_kwargs(), {})


if __name__ == "__main__":
    unittest.main()
