import json
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml
from jsonschema import Draft202012Validator

from backend.app import _rate_clients, dispatch_request
from backend.shutter import Shutter


WEBHOOK_OPERATIONS = (
    ("/api/v1/webhooks", "post"),
    ("/api/v1/webhooks/{id}", "get"),
    ("/api/v1/webhooks/{id}", "put"),
    ("/api/v1/webhooks/{id}", "delete"),
    ("/api/v1/webhooks/{id}/rotate", "post"),
    ("/api/v1/webhooks/{id}/schedule", "get"),
    ("/api/v1/webhooks/{id}/schedule", "put"),
    ("/api/v1/webhooks/{id}/schedule", "delete"),
    ("/api/v1/webhooks/{id}/template", "get"),
    ("/api/v1/webhooks/{id}/template", "put"),
    ("/api/v1/webhooks/{id}/template", "delete"),
    ("/api/v1/webhooks/{id}/template/preview", "post"),
    ("/api/v1/webhooks/{id}/test", "post"),
    ("/api/v1/webhooks/{id}/deliveries", "get"),
)

BODY_LIMIT_OPERATIONS = (
    ("/api/v1/webhooks", "post"),
    ("/api/v1/webhooks/{id}", "put"),
    ("/api/v1/webhooks/{id}/rotate", "post"),
    ("/api/v1/webhooks/{id}/schedule", "put"),
    ("/api/v1/webhooks/{id}/template", "put"),
    ("/api/v1/webhooks/{id}/template/preview", "post"),
    ("/api/v1/webhooks/{id}/test", "post"),
)


class WebhookErrorContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spec = yaml.safe_load(
            (Path(__file__).resolve().parents[1] / "docs" / "openapi.yaml")
            .read_text(encoding="utf-8")
        )
        cls.error_validator = Draft202012Validator(cls.spec["components"]["schemas"]["Error"])

    def setUp(self):
        _rate_clients.clear()
        self.addCleanup(_rate_clients.clear)
        store = patch("backend.app._webhook_store", return_value=None)
        store.start()
        self.addCleanup(store.stop)

    def concrete_path(self, path):
        return path.replace("{id}", "a" * 24)

    def test_oversized_bodies_match_documented_413_contract(self):
        for path, method in BODY_LIMIT_OPERATIONS:
            with self.subTest(method=method.upper(), path=path):
                operation = self.spec["paths"][path][method]
                response = operation["responses"]["413"]
                self.assertEqual(
                    response["content"]["application/json"]["schema"]["$ref"],
                    "#/components/schemas/Error",
                )

                status, _, body = dispatch_request(
                    method.upper(),
                    self.concrete_path(path),
                    "",
                    request_body=b"x" * 4097,
                    shutter_instance=Shutter(max_requests=0, max_load=0),
                )
                payload = json.loads(body)
                self.assertEqual(status, 413)
                self.assertEqual(payload["code"], "payload_too_large")
                self.error_validator.validate(payload)

    def test_all_documented_webhook_operations_match_429_contract(self):
        for path, method in WEBHOOK_OPERATIONS:
            with self.subTest(method=method.upper(), path=path):
                response = self.spec["paths"][path][method]["responses"]["429"]
                self.assertEqual(
                    response["$ref"], "#/components/responses/TooManyRequests"
                )
                client = f"webhook-error-contract:{method}:{path}"

                for _ in range(60):
                    dispatch_request(
                        method.upper(),
                        self.concrete_path(path),
                        "",
                        client=client,
                        shutter_instance=Shutter(max_requests=0, max_load=0),
                    )
                status, headers, body = dispatch_request(
                    method.upper(),
                    self.concrete_path(path),
                    "",
                    client=client,
                    shutter_instance=Shutter(max_requests=0, max_load=0),
                )
                payload = json.loads(body)
                self.assertEqual(status, 429)
                self.assertEqual(payload["code"], "rate_limited")
                self.assertIn("Retry-After", headers)
                self.assertTrue(headers["Retry-After"].isdigit())
                self.error_validator.validate(payload)


if __name__ == "__main__":
    unittest.main()
