import unittest
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError
from urllib.request import Request

from backend import comcigan_proxy


class ComciganProxyTests(unittest.TestCase):
    def setUp(self):
        self.original_configured = comcigan_proxy._configured
        comcigan_proxy._configured = False
        self.addCleanup(setattr, comcigan_proxy, "_configured", self.original_configured)

    def test_shared_budget_limits_subsequent_requests_and_stops_at_deadline(self):
        import pycomcigan.helpers as helpers
        original = helpers.urlopen
        self.addCleanup(setattr, helpers, "urlopen", original)
        opener = Mock()
        clock = [100.0]
        with patch.dict("os.environ", {"OPENCIGAN_COMCIGAN_PROXY": "http://127.0.0.1:18084"}), \
             patch.object(comcigan_proxy, "build_opener", return_value=opener), \
             patch.object(comcigan_proxy.time, "monotonic", side_effect=lambda: clock[0]):
            comcigan_proxy.configure_comcigan_proxy()

            @comcigan_proxy.with_comcigan_budget
            def lookup():
                helpers.urlopen(Request("http://comci.net:4082/st"))
                clock[0] += 25
                helpers.urlopen(Request("http://comci.net:4082/data"))
                clock[0] += 10
                with self.assertRaises(TimeoutError):
                    helpers.urlopen(Request("http://comci.net:4082/data"))

            lookup()
        self.assertEqual([call.kwargs["timeout"] for call in opener.open.call_args_list], [30, 10])
        self.assertIsNone(comcigan_proxy._deadline.get())

    def test_shared_budget_limits_a_delayed_second_proxy_response(self):
        import pycomcigan.helpers as helpers
        original = helpers.urlopen
        self.addCleanup(setattr, helpers, "urlopen", original)
        release = threading.Event()
        calls = []

        class SlowSecondResponse(BaseHTTPRequestHandler):
            def do_GET(self):
                calls.append(self.path)
                if len(calls) == 2:
                    release.wait(1)
                self.send_response(200)
                self.end_headers()

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), SlowSecondResponse)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with patch.dict("os.environ", {"OPENCIGAN_COMCIGAN_PROXY": f"http://127.0.0.1:{server.server_port}"}), \
                 patch.object(comcigan_proxy, "UPSTREAM_BUDGET_SECONDS", 0.2):
                comcigan_proxy.configure_comcigan_proxy()

                @comcigan_proxy.with_comcigan_budget
                def lookup():
                    with helpers.urlopen(Request("http://comci.net:4082/st")) as response:
                        response.read()
                    helpers.urlopen(Request("http://comci.net:4082/data"))

                with self.assertRaises((TimeoutError, URLError)):
                    lookup()
            self.assertEqual(len(calls), 2)
        finally:
            release.set()
            server.shutdown()
            server.server_close()
            thread.join()

    def test_proxy_is_scoped_to_comcigan_and_never_falls_back(self):
        import pycomcigan.helpers as helpers
        original = helpers.urlopen
        self.addCleanup(setattr, helpers, "urlopen", original)
        opener = Mock()
        opener.open.side_effect = OSError("proxy down")
        with patch.dict("os.environ", {"OPENCIGAN_COMCIGAN_PROXY": "http://127.0.0.1:18084", "no_proxy": "comci.net"}), \
             patch.object(comcigan_proxy, "build_opener", return_value=opener):
            comcigan_proxy.configure_comcigan_proxy()
            with self.assertRaisesRegex(OSError, "proxy down"):
                helpers.urlopen(Request("http://comci.net:4082/st"), timeout=30)
            opener.open.assert_called_once()
            self.assertEqual(opener.open.call_args.args[0].host, "127.0.0.1:18084")
            with self.assertRaises(ValueError):
                helpers.urlopen(Request("http://example.org/"))

    def test_remote_proxy_is_rejected(self):
        with patch.dict("os.environ", {"OPENCIGAN_COMCIGAN_PROXY": "http://example.org:8080"}):
            with self.assertRaises(ValueError):
                comcigan_proxy.configure_comcigan_proxy()

    def test_header_timing_records_only_stage_and_duration_on_success_and_failure(self):
        import pycomcigan.helpers as helpers
        original = helpers.urlopen
        self.addCleanup(setattr, helpers, "urlopen", original)
        opener = Mock()
        with patch.dict("os.environ", {"OPENCIGAN_COMCIGAN_PROXY": "http://127.0.0.1:18084"}), \
             patch.object(comcigan_proxy, "build_opener", return_value=opener), \
             patch.object(comcigan_proxy.time, "monotonic", side_effect=[10.0, 10.25, 20.0, 20.5]):
            comcigan_proxy.configure_comcigan_proxy()
            with self.assertLogs("opensigan.comcigan_proxy", level="INFO") as logs:
                helpers.urlopen(Request("http://comci.net:4082/st?private=secret"))
                opener.open.side_effect = TimeoutError("private details")
                with self.assertRaises(TimeoutError):
                    helpers.urlopen(Request("http://comci.net:4082/private?school=secret"))
            self.assertIn("stage=service_page duration_ms=250.0 result=success timeout_s=30", logs.output[0])
            self.assertIn("stage=data duration_ms=500.0 result=timeout timeout_s=30", logs.output[1])
            self.assertEqual(opener.open.call_args.kwargs['timeout'], 30)
            for line in logs.output:
                for private in ("secret", "school", "comci.net", "private details"):
                    self.assertNotIn(private, line)

    def test_wrapped_timeout_and_network_error_are_distinguished_without_error_details(self):
        import pycomcigan.helpers as helpers
        original = helpers.urlopen
        self.addCleanup(setattr, helpers, "urlopen", original)
        opener = Mock()
        with patch.dict("os.environ", {"OPENCIGAN_COMCIGAN_PROXY": "http://127.0.0.1:18084"}), \
             patch.object(comcigan_proxy, "build_opener", return_value=opener):
            comcigan_proxy.configure_comcigan_proxy()
            for reason, result in ((TimeoutError("private"), "timeout"), (OSError("private"), "network_error")):
                with self.subTest(result=result):
                    opener.open.side_effect = URLError(reason)
                    with self.assertLogs("opensigan.comcigan_proxy", level="INFO") as logs:
                        with self.assertRaises(URLError):
                            helpers.urlopen(Request("http://comci.net:4082/st?school=secret"))
                    self.assertIn(f"result={result} timeout_s=30", logs.output[0])
                    self.assertNotIn("secret", logs.output[0])
                    self.assertNotIn("private", logs.output[0])

    def test_post_body_and_token_pass_through_local_proxy(self):
        import pycomcigan.helpers as helpers
        original = helpers.urlopen
        self.addCleanup(setattr, helpers, "urlopen", original)
        received = []

        class LocalProxy(BaseHTTPRequestHandler):
            def do_POST(self):
                received.append((self.path, self.headers.get("Content-Type"),
                                 self.headers.get("X-Hour-Token"),
                                 self.rfile.read(int(self.headers["Content-Length"]))))
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{}')

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), LocalProxy)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            proxy = f"http://127.0.0.1:{server.server_port}"
            with patch.dict("os.environ", {"OPENCIGAN_COMCIGAN_PROXY": proxy, "no_proxy": "comci.net"}):
                comcigan_proxy.configure_comcigan_proxy()
                # This test verifies the proxy itself, so it builds a
                # standard Request and calls the replaced transport
                # directly instead of entering through a pycomcigan
                # helper; internal helper signatures must not affect it.
                request = Request("http://comci.net:4082/12345", data=b"encoded-body",
                                  headers={"Content-Type": "text/plain; charset=UTF-8",
                                           "X-Hour-Token": "test-token"})
                with self.assertLogs("opensigan.comcigan_proxy", level="INFO") as logs:
                    response = helpers.urlopen(request, timeout=30)
                    text = response.read().decode("UTF-8")
                    response.close()
            self.assertEqual(text, "{}")
            self.assertEqual(received, [("http://comci.net:4082/12345", "text/plain; charset=UTF-8",
                                         "test-token", b"encoded-body")])
            self.assertIn("stage=data", logs.output[0])
            self.assertNotIn("test-token", logs.output[0])
            self.assertNotIn("encoded-body", logs.output[0])
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_proxy_header_wait_obeys_connection_timeout(self):
        import pycomcigan.helpers as helpers
        original = helpers.urlopen
        self.addCleanup(setattr, helpers, "urlopen", original)
        release = threading.Event()
        started = threading.Event()

        class SlowProxy(BaseHTTPRequestHandler):
            def do_GET(self):
                started.set()
                release.wait(2)

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), SlowProxy)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            proxy = f"http://127.0.0.1:{server.server_port}"
            with patch.dict("os.environ", {"OPENCIGAN_COMCIGAN_PROXY": proxy}):
                comcigan_proxy.configure_comcigan_proxy()
                with self.assertLogs("opensigan.comcigan_proxy", level="INFO") as logs:
                    with self.assertRaises((TimeoutError, URLError)):
                        helpers.urlopen(Request("http://comci.net:4082/st"), timeout=0.15)
                self.assertTrue(started.is_set())
                self.assertIn("result=timeout timeout_s=0.15", logs.output[0])
        finally:
            release.set()
            server.shutdown()
            server.server_close()
            thread.join()

    def test_rejection_status_logged_without_request_details(self):
        import pycomcigan.helpers as helpers
        original = helpers.urlopen
        self.addCleanup(setattr, helpers, "urlopen", original)
        opener = Mock()
        with patch.dict("os.environ", {"OPENCIGAN_COMCIGAN_PROXY": "http://127.0.0.1:18084"}), \
             patch.object(comcigan_proxy, "build_opener", return_value=opener):
            comcigan_proxy.configure_comcigan_proxy()
            for status in (403, 429):
                with self.subTest(status=status):
                    error = HTTPError("http://comci.net:4082/?secret=token", status, "private message", {}, None)
                    self.addCleanup(error.close)
                    opener.open.side_effect = error
                    with self.assertLogs("opensigan.comcigan_proxy", level="WARNING") as logs:
                        with self.assertRaises(HTTPError) as raised:
                            helpers.urlopen(Request("http://comci.net:4082/?secret=token"))
                    self.assertIs(raised.exception, error)
                    self.assertIn(f"upstream_http_status={status}", logs.output[0])
                    for private in ("secret", "token", "private message", "comci.net"):
                        self.assertNotIn(private, logs.output[0])

    def test_disabled_does_not_change_urllib(self):
        import pycomcigan.helpers as helpers
        original = helpers.urlopen
        with patch.dict("os.environ", {"OPENCIGAN_COMCIGAN_PROXY": ""}):
            comcigan_proxy.configure_comcigan_proxy()
        self.assertIs(helpers.urlopen, original)
