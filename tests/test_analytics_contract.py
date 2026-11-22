import json
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import yaml
from jsonschema import Draft202012Validator

from backend.app import dispatch_request


class AnalyticsContractTests(unittest.TestCase):
    def test_pageview_success_and_errors_match_openapi(self):
        spec = yaml.safe_load((Path(__file__).resolve().parents[1] / "docs" / "openapi.yaml").read_text(encoding="utf-8"))
        path = "/api/v1/analytics/pageview"
        operation = spec["paths"][path]["post"]
        payload = {"visitorId": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
                   "sessionId": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb", "page": "/"}
        Draft202012Validator(operation["requestBody"]["content"]["application/json"]["schema"]).validate(payload)
        cases = ((202, json.dumps(payload).encode(), Mock(), None),
                 (400, b"[]", Mock(), None),
                 (413, b"x" * 4097, Mock(), None),
                 (503, b"{}", None, None),
                 (429, b"{}", Mock(), 17))
        for expected, body, store, retry in cases:
            with self.subTest(status=expected), patch("backend.app._analytics_store", return_value=store), \
                    patch("backend.app._rate_allowed", return_value=retry):
                status, headers, response = dispatch_request(
                    "POST", path, "", client="test", request_body=body,
                    shutter_instance=Mock(check=Mock(return_value=(True, 0))))
                self.assertEqual(status, expected)
                documented = operation["responses"][str(status)]
                if "$ref" in documented:
                    documented = spec["components"]["responses"][documented["$ref"].rsplit("/", 1)[-1]]
                schema = documented["content"]["application/json"]["schema"]
                Draft202012Validator({"$ref": "#/$defs/response", "$defs": {"response": schema},
                                      "components": spec["components"]}).validate(json.loads(response))
                if expected == 429:
                    self.assertEqual(headers["Retry-After"], "17")


if __name__ == "__main__":
    unittest.main()
