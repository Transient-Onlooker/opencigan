import json
import os
import sys
import threading
import time
import traceback
import unittest
import urllib.error
from unittest.mock import patch
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from opensigan import OpensiganClient, OpensiganError


class MockServerHandler(BaseHTTPRequestHandler):
    last_request_path = ""
    last_request_headers = {}

    def log_message(self, format, *args):
        pass  # suppress console logging

    def do_GET(self):
        MockServerHandler.last_request_path = self.path
        MockServerHandler.last_request_headers = {k: v for k, v in self.headers.items()}
        parts = urlsplit(self.path)
        path = parts.path
        query = parse_qs(parts.query)
        case = None
        if path.startswith("/case/"):
            _, _, case, path = path.split("/", 3)
            path = "/" + path

        if path == "/api/v1/neis/schools":
            body = b'{"schools":[],"stale":false}'
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif path == "/api/v1/status" and case:
            bodies = {"invalid": b"<html>bad JSON</html>", "empty": b"", "utf8": b"\xff",
                      "null": b"null", "array": b"[]", "error": b"bad JSON"}
            body = bodies.get(case, b"{")
            self.send_response(502 if case == "error" else 200)
            self.send_header("Content-Length", str(len(body) + (1 if case == "slow" else 0)))
            self.end_headers()
            self.wfile.write(body)
            self.wfile.flush()
            if case == "slow":
                time.sleep(0.15)
        elif path == "/api/v1/status":
            body = json.dumps({"status": "ok", "scope": "process liveness"}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif path == "/api/v1/schools":
            body = json.dumps({"schools": [{"id": "2:학교", "name": query.get("q", [""])[0]}], "stale": False}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif path == "/api/v1/timetable":
            if query.get("week", [""])[0] == "2026-11-17":
                body = json.dumps({"error": "주 시작일이 올바르지 않습니다", "code": "invalid_request"}).encode("utf-8")
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                body = json.dumps({"schoolId": query.get("school", [""])[0], "records": [], "stale": False}).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
        elif path == "/api/v1/timetable.ics":
            etag = '"test-etag-123"'
            if self.headers.get("If-None-Match") == etag:
                self.send_response(304)
                self.send_header("ETag", etag)
                self.end_headers()
            else:
                body = b"BEGIN:VCALENDAR\r\nEND:VCALENDAR"
                self.send_response(200)
                self.send_header("Content-Type", "text/calendar; charset=utf-8")
                self.send_header("ETag", etag)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
        elif path == "/api/v1/timetable/history":
            if query.get("school", [""])[0] == "disabled":
                body = json.dumps({"error": "변경 이력 저장이 활성화되지 않았습니다", "code": "history_disabled"}).encode("utf-8")
                self.send_response(503)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                body = json.dumps({"changes": [], "nextCursor": None}).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
        elif path == "/api/v1/meals":
            body = json.dumps({"meals": [], "stale": False}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            body = json.dumps({"error": "요청한 경로가 없습니다", "code": "not_found"}).encode("utf-8")
            self.send_response(404)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)


class TestOpensiganPythonClient(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), MockServerHandler)
        cls.port = cls.server.server_port
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.port}"
        cls.client = OpensiganClient(base_url=cls.base_url, timeout=5.0)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def test_invalid_json_and_http_fallback(self):
        for case in ("invalid", "empty", "utf8", "null", "array"):
            with self.subTest(case=case):
                client = OpensiganClient(self.base_url + "/case/" + case)
                with self.assertRaises(OpensiganError) as ctx:
                    client.get_status()
                self.assertEqual(ctx.exception.status, 200)
                self.assertEqual(ctx.exception.code, "invalid_response")
        with self.assertRaises(OpensiganError) as ctx:
            OpensiganClient(self.base_url + "/case/error").get_status()
        self.assertEqual(ctx.exception.status, 502)
        self.assertIsNone(ctx.exception.code)

    def test_retry_after_is_preserved_for_json_and_calendar_errors(self):
        cases = [(429, '30', b'{"error":"limited","code":"rate_limited"}'),
                 (503, 'Wed, 25 Nov 2026 12:00:00 GMT', b'upstream unavailable')]
        for status, retry_after, body in cases:
            for calendar in (False, True):
                with self.subTest(status=status, calendar=calendar), patch.object(
                    self.client, '_request', return_value=(status, {'Retry-After': retry_after}, body)
                ), self.assertRaises(OpensiganError) as ctx:
                    if calendar:
                        self.client.get_timetable_ics('1:school', 1, 1)
                    else:
                        self.client.get_status()
                self.assertEqual(ctx.exception.status, status)
                self.assertEqual(ctx.exception.retry_after, retry_after)

    def test_timeout_and_sanitized_transport_error(self):
        with self.assertRaises(OpensiganError) as ctx:
            OpensiganClient(self.base_url + "/case/slow").get_status(timeout=0.03)
        self.assertTrue(ctx.exception.is_timeout)
        raw_error = urllib.error.URLError("GET https://example.com/?token=secret")
        with patch("urllib.request.urlopen", side_effect=raw_error):
            try:
                self.client.get_status()
            except OpensiganError as error:
                self.assertTrue(error.is_network_error)
                self.assertNotIn("secret", "".join(traceback.format_exception(error)))
            else:
                self.fail("Expected a structured transport error")

    def test_invalid_configuration(self):
        for base_url in ("/relative", "file:///tmp/feed", "https://user:secret@example.com",
                         "https://example.com?token=secret", "https://example.com#secret",
                         "https://example.com:bad"):
            with self.subTest(base_url=base_url), self.assertRaises(OpensiganError) as ctx:
                OpensiganClient(base_url=base_url)
            self.assertEqual(ctx.exception.code, "invalid_config")
            self.assertNotIn("secret", str(ctx.exception))
        for timeout in (0, -1, float("nan"), float("inf"), True, "invalid"):
            with self.subTest(timeout=timeout), self.assertRaises(OpensiganError) as ctx:
                OpensiganClient(timeout=timeout)
            self.assertEqual(ctx.exception.code, "invalid_config")
            with self.assertRaises(OpensiganError):
                self.client.get_status(timeout=timeout)

    def test_query_encoding_and_routes(self):
        # 1. Status
        res = self.client.get_status()
        self.assertEqual(res["status"], "ok")
        self.assertEqual(MockServerHandler.last_request_path, "/api/v1/status")
        self.assertEqual(
            MockServerHandler.last_request_headers.get("User-Agent"),
            "OpenCigan-Python-Client (+https://github.com/Transient-Onlooker/opencigan)",
        )
        self.client.search_neis_schools("서울&학교")
        self.assertEqual(parse_qs(urlsplit(MockServerHandler.last_request_path).query)["q"], ["서울&학교"])

        # 2. School search with special chars
        search_res = self.client.search_schools("서울&경기+고등학교#1 100%")
        self.assertEqual(search_res["schools"][0]["name"], "서울&경기+고등학교#1 100%")
        self.assertIn("q=%EC%84%9C%EC%9A%B8%26%EA%B2%BD%EA%B8%B0%2B%EA%B3%A0%EB%93%B1%ED%95%99%EA%B5%90%231+100%25", MockServerHandler.last_request_path)

        # 3. Timetable query with filters
        tt = self.client.get_timetable("1234:한국+고등학교", "2026-11-16", grade=2, classroom=3, teacher="김선생")
        self.assertEqual(tt["schoolId"], "1234:한국+고등학교")
        parts = urlsplit(MockServerHandler.last_request_path)
        q = parse_qs(parts.query)
        self.assertEqual(q["school"][0], "1234:한국+고등학교")
        self.assertEqual(q["week"][0], "2026-11-16")
        self.assertEqual(q["grade"][0], "2")
        self.assertEqual(q["class"][0], "3")
        self.assertEqual(q["teacher"][0], "김선생")

        # 4. Meals with 7-day range
        meals = self.client.get_meals("B10:1234567", "2026-11-16", "2026-11-22")
        parts = urlsplit(MockServerHandler.last_request_path)
        q = parse_qs(parts.query)
        self.assertEqual(q["school"][0], "B10:1234567")
        self.assertEqual(q["from"][0], "2026-11-16")
        self.assertEqual(q["to"][0], "2026-11-22")

        # 5. History with cursor
        hist = self.client.get_timetable_history("1234:학교", "2026-11-16", cursor="cursor/token+123==")
        parts = urlsplit(MockServerHandler.last_request_path)
        q = parse_qs(parts.query)
        self.assertEqual(q["cursor"][0], "cursor/token+123==")

        # 6. ICS URL generation
        ics_url = self.client.get_timetable_ics_url("1234:학교", grade=1, classroom=2, weeks=2, mode="periods")
        self.assertIn("/api/v1/timetable.ics?", ics_url)
        self.assertIn("weeks=2", ics_url)
        self.assertIn("mode=periods", ics_url)
        ics_url = self.client.get_timetable_ics_url("1234:학교", 1, 2, weeks=9, mode="unsupported")
        self.assertEqual(parse_qs(urlsplit(ics_url).query)["weeks"], ["9"])
        self.assertEqual(parse_qs(urlsplit(ics_url).query)["mode"], ["unsupported"])
        self.client.get_timetable_ics("1234:학교", 1, 2, teacher="김&Lee", mode="summary")
        query = parse_qs(urlsplit(MockServerHandler.last_request_path).query)
        self.assertEqual(query["teacher"], ["김&Lee"])
        self.assertEqual(query["mode"], ["summary"])
        timed_url = self.client.get_timetable_ics_url(
            "1234:학교", 1, 2, mode="timed", times="1:0900-0950,2:1000-1050"
        )
        self.assertEqual(parse_qs(urlsplit(timed_url).query)["mode"], ["timed"])
        self.assertEqual(parse_qs(urlsplit(timed_url).query)["times"], ["1:0900-0950,2:1000-1050"])
        self.client.get_timetable_ics(
            "1234:학교", 1, 2, mode="timed", times="1:0900-0950,2:1000-1050"
        )
        query = parse_qs(urlsplit(MockServerHandler.last_request_path).query)
        self.assertEqual(query["mode"], ["timed"])
        self.assertEqual(query["times"], ["1:0900-0950,2:1000-1050"])
        self.assertIn("times=1%3A0900-0950%2C2%3A1000-1050", MockServerHandler.last_request_path)

    def test_error_handling(self):
        # 400 invalid_request error
        with self.assertRaises(OpensiganError) as ctx:
            self.client.get_timetable("1234:학교", "2026-11-17")
        self.assertEqual(ctx.exception.status, 400)
        self.assertEqual(ctx.exception.code, "invalid_request")
        self.assertIn("주 시작일이 올바르지 않습니다", str(ctx.exception))

        # 503 history_disabled error
        with self.assertRaises(OpensiganError) as ctx:
            self.client.get_timetable_history("disabled", "2026-11-16")
        self.assertEqual(ctx.exception.status, 503)
        self.assertEqual(ctx.exception.code, "history_disabled")

        # ICS 304 conditional request
        content, not_modified, etag = self.client.get_timetable_ics("1234:학교", 1, 1)
        self.assertFalse(not_modified)
        self.assertEqual(etag, '"test-etag-123"')
        self.assertIn("BEGIN:VCALENDAR", content)

        cached, not_modified_2, etag_2 = self.client.get_timetable_ics("1234:학교", 1, 1, if_none_match='"test-etag-123"')
        self.assertTrue(not_modified_2)
        self.assertIsNone(cached)
        self.assertEqual(etag_2, '"test-etag-123"')

        # Network connection failure
        bad_client = OpensiganClient(base_url="http://127.0.0.1:1", timeout=0.5)
        with self.assertRaises(OpensiganError) as ctx:
            bad_client.get_status()
        self.assertTrue(ctx.exception.is_network_error or ctx.exception.is_timeout)


if __name__ == "__main__":
    unittest.main()
