import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.app import _rate_clients, dispatch_request, make_app


class SuggestionIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = str(Path(self.temp.name) / "suggestions.sqlite")
        _rate_clients.clear()

    def request(self, method, path, data=None, token=None):
        body = json.dumps(data).encode() if data is not None else b""
        environ = {"REQUEST_METHOD": method, "PATH_INFO": path, "QUERY_STRING": "",
                   "REMOTE_ADDR": "127.0.0.1", "CONTENT_LENGTH": str(len(body)),
                   "wsgi.input": io.BytesIO(body)}
        if token:
            environ["HTTP_AUTHORIZATION"] = "Bearer " + token
        statuses = []
        result = b"".join(make_app()(environ, lambda status, headers: statuses.append(status)))
        return statuses[0], json.loads(result)

    def test_disabled_does_not_create_database(self):
        with patch.dict("os.environ", {"OPENCIGAN_SUGGESTIONS_ENABLED": "", "OPENCIGAN_SUGGESTION_DB": self.db}):
            status, _ = self.request("POST", "/api/v1/suggestions", {"title": "A", "description": "B"})
        self.assertEqual(status, "503 Service Unavailable")
        self.assertFalse(Path(self.db).exists())

    def test_existing_database_is_not_reused(self):
        with patch.dict("os.environ", {"OPENCIGAN_SUGGESTIONS_ENABLED": "1", "OPENCIGAN_SUGGESTION_DB": self.db,
                                       "OPENCIGAN_HISTORY_DB": self.db}):
            status, _ = self.request("POST", "/api/v1/suggestions", {"title": "A", "description": "B"})
        self.assertEqual(status, "503 Service Unavailable")
        self.assertFalse(Path(self.db).exists())

    def test_wsgi_submission_and_private_access(self):
        with patch.dict("os.environ", {"OPENCIGAN_SUGGESTIONS_ENABLED": "1", "OPENCIGAN_SUGGESTION_DB": self.db}):
            status, created = self.request("POST", "/api/v1/suggestions", {"title": "A", "description": "B"})
            self.assertEqual(status, "201 Created")
            self.assertEqual(self.request("POST", "/api/v1/suggestions", {"title": "A", "description": "B"})[0], "409 Conflict")
            path = "/api/v1/suggestions/" + created["id"]
            self.assertEqual(self.request("GET", path, token=created["token"])[0], "200 OK")
            self.assertEqual(self.request("GET", path, token="incorrect")[0], "401 Unauthorized")
            self.assertEqual(self.request("GET", "/api/v1/suggestions")[1]["suggestions"], [])

    def test_wsgi_admin_approval_and_permissions(self):
        token = "admin-test-token-0123456789abcdef"
        with patch.dict("os.environ", {"OPENCIGAN_SUGGESTIONS_ENABLED": "1", "OPENCIGAN_SUGGESTION_DB": self.db,
                                       "OPENCIGAN_SUGGESTION_ADMIN_TOKEN": token}):
            _, created = self.request("POST", "/api/v1/suggestions", {"title": "A", "description": "B"})
            path = "/api/v1/admin/suggestions/" + created["id"]
            self.assertEqual(self.request("PATCH", path, {"status": "approved"}, token="incorrect")[0], "401 Unauthorized")
            self.assertEqual(self.request("GET", "/api/v1/suggestions")[1]["suggestions"], [])
            self.assertEqual(self.request("PATCH", path, {"status": "approved"}, token=token)[0], "200 OK")
            self.assertEqual(len(self.request("GET", "/api/v1/suggestions")[1]["suggestions"]), 1)

    def test_admin_preflight_allows_patch_and_delete(self):
        status, headers, _ = dispatch_request("OPTIONS", "/api/v1/admin/suggestions/" + "a" * 24, "")
        self.assertEqual(status, 204)
        self.assertIn("PATCH", headers["Access-Control-Allow-Methods"])
        self.assertIn("DELETE", headers["Access-Control-Allow-Methods"])


if __name__ == "__main__":
    unittest.main()
