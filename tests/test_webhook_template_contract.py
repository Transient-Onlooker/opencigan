import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml
from jsonschema import Draft202012Validator

from backend.app import dispatch_request
from backend.webhook_store import WebhookStore


class WebhookTemplateContractTests(unittest.TestCase):
    def test_real_template_responses_match_openapi_for_both_providers(self):
        spec = yaml.safe_load((Path(__file__).resolve().parents[1] / "docs" / "openapi.yaml").read_text(encoding="utf-8"))
        temp_root = Path.home() / "AppData" / "Local" / "Temp" if os.name == "nt" else None
        with tempfile.TemporaryDirectory(dir=temp_root) as directory:
            store = WebhookStore(Path(directory) / "history.sqlite")
            for destination in ("https://discord.com/api/webhooks/123/secret",
                                "https://chat.googleapis.com/v1/spaces/abc/messages?key=K&token=T"):
                subscription = store.create("2:Example", 2, 3, destination)
                path = f"/api/v1/webhooks/{subscription['id']}/template"
                headers = {"Authorization": f"Bearer {subscription['token']}"}
                operations = [("GET", path, None),
                              ("PUT", path, {"template": "{school} {period}", "discordEmbed": False}),
                              ("POST", path + "/preview", {"template": "{school} {period}", "discordEmbed": False})]
                if subscription["provider"] == "discord":
                    operations.append(("POST", path + "/preview", {"template": "{school}", "discordEmbed": True}))
                operations.append(("DELETE", path, None))
                for method, actual_path, payload in operations:
                    documented = "/api/v1/webhooks/{id}/template" + ("/preview" if actual_path.endswith("/preview") else "")
                    with self.subTest(provider=subscription["provider"], method=method, path=documented, payload=payload):
                        body = json.dumps(payload).encode() if payload is not None else None
                        with patch("backend.app._webhook_store", return_value=store):
                            status, _, result = dispatch_request(method, actual_path, "", request_body=body, request_headers=headers)
                        self.assertEqual(status, 200)
                        schema = spec["paths"][documented][method.lower()]["responses"]["200"]["content"]["application/json"]["schema"]
                        Draft202012Validator(schema).validate(json.loads(result))
            self.assertEqual(store.deliveries(subscription["id"], subscription["token"]), [])


if __name__ == "__main__":
    unittest.main()
