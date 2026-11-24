import json
import unittest
from unittest.mock import patch

from backend.internal_api import application


class InternalApiTests(unittest.TestCase):
    def request(self, auth="Bearer secret", query="school=1%3AExample&week=2026-11-23"):
        result = {}
        def start_response(status, headers):
            result.update(status=status, headers=dict(headers))
        environ = {"HTTP_AUTHORIZATION": auth, "PATH_INFO": "/internal/v1/timetable",
                   "REQUEST_METHOD": "GET", "QUERY_STRING": query}
        result["body"] = json.loads(b"".join(application(environ, start_response)))
        return result

    @patch.dict("os.environ", {"OPENCIGAN_INTERNAL_TOKEN": "secret"})
    @patch("backend.internal_api.fetch_timetable")
    def test_authentication_empty_result_and_failure_are_distinct(self, fetch):
        self.assertEqual(self.request(auth="Bearer wrong")["status"], "401 Unauthorized")
        fetch.assert_not_called()
        fetch.return_value = {"records": []}
        result = self.request()
        self.assertEqual(result["status"], "200 OK")
        self.assertEqual(result["body"]["records"], [])
        self.assertEqual(result["headers"]["Cache-Control"], "no-store")
        fetch.assert_called_once_with("1:Example", "2026-11-23", include_original=True)
        fetch.side_effect = RuntimeError("private upstream detail")
        self.assertEqual(self.request()["body"]["code"], "upstream_unavailable")

    @patch.dict("os.environ", {"OPENCIGAN_INTERNAL_TOKEN": "secret"})
    @patch("backend.internal_api.fetch_timetable")
    def test_duplicate_or_missing_query_is_rejected(self, fetch):
        for query in ("school=1%3Ax", "school=1%3Ax&week=x&week=y"):
            self.assertEqual(self.request(query=query)["status"], "400 Bad Request")
        fetch.assert_not_called()
