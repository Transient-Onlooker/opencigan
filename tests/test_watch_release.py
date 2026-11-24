import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from deploy.watch_release import latest_release, poll


@unittest.skipIf(os.name == "nt", "requires Linux file locking")
class WatchReleaseTests(unittest.TestCase):
    @patch("deploy.watch_release.load_release")
    @patch("deploy.watch_release.api")
    def test_resolves_tag_and_validates_manifest(self, api, load):
        api.side_effect = [{"tag_name": "1.4.6+autofix.1", "draft": False, "prerelease": False},
                           {"object": {"type": "tag", "sha": "b" * 40}},
                           {"object": {"type": "commit", "sha": "a" * 40}}]
        self.assertEqual(latest_release(), ("1.4.6+autofix.1", "a" * 40))
        load.assert_called_once_with("1.4.6+autofix.1", "a" * 40)

    @patch("deploy.watch_release.deploy")
    @patch("deploy.watch_release.latest_release")
    @patch("deploy.watch_release.retry_pending_pin", return_value={"pinSync": "synced"})
    def test_retry_pin_before_considering_new_release(self, retry, latest, deploy):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "deployment-status.json").write_text(json.dumps({"success": True, "pinSync": "failed"}))
            self.assertEqual(poll(root, "/release", "1:A", "2026-11-23"), {"pinSync": "synced"})
            retry.assert_called_once()
            latest.assert_not_called()
            deploy.assert_not_called()

    @patch("deploy.watch_release.deploy", return_value={"success": True})
    @patch("deploy.watch_release.latest_release", return_value=("1.4.6", "a" * 40))
    def test_new_release_uses_existing_deploy_path(self, latest, deploy):
        with tempfile.TemporaryDirectory() as temporary:
            self.assertTrue(poll(temporary, "/release", "1:A", "2026-11-23")["success"])
            deploy.assert_called_once_with("1.4.6", "a" * 40, Path(temporary), "/release", "1:A", "2026-11-23")
