import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from deploy.fork_manifest import REPOSITORY, load_release, validate_manifest, verify_package


class ForkManifestTests(unittest.TestCase):
    def setUp(self):
        self.sha = "a" * 40
        self.content = b"example package\n"
        self.manifest = {"repo": REPOSITORY, "tag": "1.4.6", "git_sha": self.sha, "version": "1.4.6",
                         "origin": "upstream", "files": {"__init__.py": hashlib.sha256(self.content).hexdigest()}}
        self.encoded = json.dumps(self.manifest).encode()
        self.url = "https://github.com/" + REPOSITORY + "/releases/download/1.4.6/deploy-manifest.json"
        self.release = {"tag_name": "1.4.6", "draft": False, "assets": [{
            "name": "deploy-manifest.json", "state": "uploaded", "browser_download_url": self.url,
            "digest": "sha256:" + hashlib.sha256(self.encoded).hexdigest()}]}

    @patch("deploy.fork_manifest.fetch")
    @patch("deploy.fork_manifest.api")
    def test_checks_release_tag_and_manifest_digest(self, api, fetch):
        api.side_effect = [self.release, {"object": {"type": "commit", "sha": self.sha}}]
        fetch.return_value = self.encoded
        self.assertEqual(load_release("1.4.6", self.sha), self.manifest)

    @patch("deploy.fork_manifest.fetch")
    @patch("deploy.fork_manifest.api")
    def test_rejects_moved_tag_or_altered_manifest(self, api, fetch):
        api.side_effect = [self.release, {"object": {"type": "commit", "sha": "b" * 40}}]
        with self.assertRaisesRegex(ValueError, "tag does not match"):
            load_release("1.4.6", self.sha)
        fetch.assert_not_called()
        api.side_effect = [self.release, {"object": {"type": "commit", "sha": self.sha}}]
        fetch.return_value = b"{}"
        with self.assertRaisesRegex(ValueError, "digest mismatch"):
            load_release("1.4.6", self.sha)

    def test_package_hash_and_unexpected_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "__init__.py").write_bytes(self.content)
            verify_package(root, self.manifest)
            (root / "extra.py").write_bytes(b"unexpected")
            with self.assertRaisesRegex(ValueError, "file list mismatch"):
                verify_package(root, self.manifest)
            (root / "extra.py").unlink()
            (root / "__init__.py").write_bytes(b"tampered")
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                verify_package(root, self.manifest)

    @patch("deploy.fork_manifest.fetch")
    @patch("deploy.fork_manifest.api")
    def test_autofix_release_manifest_and_tag_are_verified(self, api, fetch):
        tag = "1.4.6+autofix.1"
        manifest = {"name": "pycomcigan", "version": tag, "git_sha": self.sha,
                    "origin": "patched", "files": {"pycomcigan/__init__.py": hashlib.sha256(self.content).hexdigest()}}
        body = json.dumps(manifest).encode()
        url = "https://github.com/" + REPOSITORY + "/releases/download/1.4.6%2Bautofix.1/deploy-manifest.json"
        release = {"tag_name": tag, "draft": False, "assets": [{"name": "deploy-manifest.json",
                   "state": "uploaded", "browser_download_url": url, "digest": "sha256:" + hashlib.sha256(body).hexdigest()}]}
        api.side_effect = [release, {"object": {"type": "commit", "sha": self.sha}}]
        fetch.return_value = body
        self.assertEqual(load_release(tag, self.sha), manifest)
        self.assertEqual(validate_manifest(manifest, tag, self.sha), {"__init__.py": hashlib.sha256(self.content).hexdigest()})
        manifest["files"]["pycomcigan/../unsafe.py"] = "a" * 64
        with self.assertRaisesRegex(ValueError, "invalid file hashes"):
            validate_manifest(manifest, tag, self.sha)
