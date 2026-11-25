import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch
from urllib.request import Request

from backend import app, comcigan_proxy
from backend.cache import Cache


class ProxyTimeoutBoundaryTests(unittest.TestCase):
    def test_body_timeout_after_headers_preserves_stale_and_backoff(self):
        import pycomcigan.helpers as helpers

        release = threading.Event()
        calls = []

        class SlowBodyProxy(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Length", "2")
                self.end_headers()
                self.wfile.flush()
                release.wait(2)

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), SlowBodyProxy)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.addCleanup(release.set)

        def fetch(school, week):
            calls.append(school)
            with helpers.urlopen(Request("http://comci.net:4082/st"), timeout=0.15) as response:
                response.read()
            return {"schoolId": school, "weekStart": week, "records": [], "stale": False}

        cache = Cache(ttl=0, retry_delay=60)
        cache.get(("timetable", "1:stale", "2026-11-09"),
                  lambda: {"schoolId": "1:stale", "weekStart": "2026-11-09", "records": [], "stale": False})
        with patch.dict("os.environ", {"OPENCIGAN_COMCIGAN_PROXY": f"http://127.0.0.1:{server.server_port}"}), \
             patch.object(helpers, "urlopen", helpers.urlopen), \
             patch.object(comcigan_proxy, "_configured", False), \
             patch.object(app, "fetch_timetable", side_effect=fetch), \
             patch.object(app, "validate_timetable_week"):
            comcigan_proxy.configure_comcigan_proxy()

            def request(school):
                return app.dispatch_request("GET", "/api/v1/timetable", f"school=1%3A{school}&week=2026-11-09", cache_instance=cache)

            with self.assertLogs("opensigan.comcigan_proxy", level="INFO") as logs:
                status, headers, body = request("slow")
                self.assertEqual(status, 503)
                self.assertEqual(json.loads(body)["code"], "upstream_unavailable")
                self.assertGreater(int(headers["Retry-After"]), 0)
                self.assertEqual(request("slow")[0], 503)
                status, _, body = request("stale")
                self.assertEqual(status, 200)
                self.assertEqual(json.loads(body)["cacheStatus"], "stale")
                self.assertTrue(json.loads(body)["stale"])
                self.assertEqual(request("stale")[0], 200)
            self.assertEqual(calls, ["1:slow", "1:stale"])
            self.assertEqual(len(logs.output), 2)
            self.assertTrue(all("result=success" in line for line in logs.output))

    def test_timeout_becomes_503_with_backoff_without_affecting_another_school(self):
        import pycomcigan.helpers as helpers

        release = threading.Event()
        started = threading.Event()
        calls = []

        class SlowProxy(BaseHTTPRequestHandler):
            def do_GET(self):
                started.set()
                release.wait(2)

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), SlowProxy)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.addCleanup(release.set)

        def fetch(school, week):
            calls.append(school)
            if school in ("1:slow", "1:stale"):
                helpers.urlopen(Request("http://comci.net:4082/st"), timeout=0.15)
            return {"schoolId": school, "weekStart": week, "records": [], "stale": False}

        cache = Cache(ttl=0, retry_delay=60)
        cache.get(("timetable", "1:stale", "2026-11-09"),
                  lambda: {"schoolId": "1:stale", "weekStart": "2026-11-09", "records": [], "stale": False})
        with patch.dict("os.environ", {"OPENCIGAN_COMCIGAN_PROXY": f"http://127.0.0.1:{server.server_port}"}), \
             patch.object(helpers, "urlopen", helpers.urlopen), \
             patch.object(comcigan_proxy, "_configured", False), \
             patch.object(app, "fetch_timetable", side_effect=fetch), \
             patch.object(app, "validate_timetable_week"):
            comcigan_proxy.configure_comcigan_proxy()

            def request(school):
                return app.dispatch_request("GET", "/api/v1/timetable", f"school=1%3A{school}&week=2026-11-09", cache_instance=cache)

            status, headers, body = request("slow")
            self.assertTrue(started.is_set())
            self.assertEqual(status, 503)
            self.assertEqual(json.loads(body)["code"], "upstream_unavailable")
            self.assertGreater(int(headers["Retry-After"]), 0)
            self.assertEqual(request("slow")[0], 503)
            self.assertEqual(calls.count("1:slow"), 1)
            status, _, body = request("stale")
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(body)["cacheStatus"], "stale")
            self.assertTrue(json.loads(body)["stale"])
            self.assertEqual(request("stale")[0], 200)
            self.assertEqual(calls.count("1:stale"), 1)
            status, _, body = request("fast")
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(body)["schoolId"], "1:fast")


if __name__ == "__main__":
    unittest.main()
