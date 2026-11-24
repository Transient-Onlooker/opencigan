import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from deploy.verify_component import verify


class ComponentVerificationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.wheel = self.root / "package.whl"
        self.wheel.write_bytes(b"test-wheel")
        self.manifest = self.root / "deploy-manifest.json"
        self.data = {"schemaVersion": 1, "repository": "hegelty/pycomcigan",
                     "kind": "official", "releaseTag": "1.4.6", "commit": "a" * 40,
                     "wheelSha256": hashlib.sha256(b"test-wheel").hexdigest()}
        self.write_manifest()

    def write_manifest(self):
        self.manifest.write_text(json.dumps(self.data), encoding="utf-8")
        self.manifest_hash = hashlib.sha256(self.manifest.read_bytes()).hexdigest()

    def run_verification(self):
        return verify(self.manifest, self.manifest_hash, self.wheel, "hegelty/pycomcigan")

    @patch("deploy.verify_component.github_json")
    def test_pinned_release_and_wheel(self, github):
        github.side_effect = [{"tag_name": "1.4.6", "draft": False},
                              {"object": {"type": "commit", "sha": "a" * 40}}]
        self.assertEqual(self.run_verification()["commit"], "a" * 40)

    @patch("deploy.verify_component.github_json")
    def test_rejects_changed_tag_and_package(self, github):
        github.side_effect = [{"tag_name": "1.4.6", "draft": False},
                              {"object": {"type": "commit", "sha": "b" * 40}}]
        with self.assertRaisesRegex(ValueError, "commit mismatch"):
            self.run_verification()
        self.wheel.write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "Wheel digest mismatch"):
            self.run_verification()

    @patch("deploy.verify_component.github_json")
    def test_rejects_untrusted_manifest_and_kind(self, github):
        with self.assertRaisesRegex(ValueError, "Manifest digest mismatch"):
            verify(self.manifest, "0" * 64, self.wheel, "hegelty/pycomcigan")
        self.data["kind"] = "fork"
        self.write_manifest()
        with self.assertRaisesRegex(ValueError, "untrusted repository"):
            self.run_verification()
        github.assert_not_called()
