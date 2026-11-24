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
    @patch("deploy.watch_release.latest_release", return_value=("1.4.6", "a" * 40))
    @patch("deploy.watch_release.retry_pending_pin", return_value={"pinSync": "synced"})
    def test_retry_pin_when_latest_is_active(self, retry, latest, deploy):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "deployment-status.json").write_text(json.dumps({"success": True, "pinSync": "failed", "activeSha": "a" * 40}))
            self.assertEqual(poll(root, "/release", "1:A", "2026-11-23"), {"pinSync": "synced"})
            retry.assert_called_once()
            latest.assert_called_once()
            deploy.assert_not_called()

    @patch("deploy.watch_release.retry_pending_pin")
    @patch("deploy.watch_release.deploy", return_value={"success": True, "activeSha": "b" * 40})
    @patch("deploy.watch_release.latest_release", return_value=("1.4.7", "b" * 40))
    def test_pending_pin_does_not_block_new_release(self, latest, deploy, retry):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "deployment-status.json").write_text(json.dumps({"success": True, "pinSync": "failed", "activeSha": "a" * 40}))
            self.assertEqual(poll(root, "/release", "1:A", "2026-11-23")["activeSha"], "b" * 40)
            deploy.assert_called_once()
            retry.assert_not_called()

    @patch("deploy.watch_release.retry_pending_pin")
    @patch("deploy.watch_release.deploy", side_effect=RuntimeError("new candidate failed"))
    @patch("deploy.watch_release.latest_release", return_value=("1.4.7", "b" * 40))
    def test_new_release_failure_still_retries_prior_pending_pin(self, latest, deploy, retry):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "deployment-status.json").write_text(json.dumps({"success": True, "pinSync": "failed", "activeSha": "a" * 40}))
            with self.assertRaisesRegex(RuntimeError, "new candidate failed"):
                poll(root, "/release", "1:A", "2026-11-23")
            deploy.assert_called_once()
            retry.assert_called_once()

    @patch("deploy.watch_release.retry_pending_pin")
    @patch("deploy.watch_release.latest_release", side_effect=RuntimeError("release lookup failed"))
    def test_release_lookup_failure_still_retries_pending_pin(self, latest, retry):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "deployment-status.json").write_text(json.dumps({"success": True, "pinSync": "failed", "activeSha": "a" * 40}))
            with self.assertRaisesRegex(RuntimeError, "release lookup failed"):
                poll(root, "/release", "1:A", "2026-11-23")
            retry.assert_called_once()

    @patch("deploy.watch_release.deploy", return_value={"success": True})
    @patch("deploy.watch_release.latest_release", return_value=("1.4.6", "a" * 40))
    def test_new_release_uses_existing_deploy_path(self, latest, deploy):
        with tempfile.TemporaryDirectory() as temporary:
            self.assertTrue(poll(temporary, "/release", "1:A", "2026-11-23")["success"])
            deploy.assert_called_once_with("1.4.6", "a" * 40, Path(temporary), "/release", "1:A", "2026-11-23")

    @patch("deploy.watch_release.deploy")
    @patch("deploy.watch_release.latest_release", return_value=("1.4.6", "a" * 40))
    def test_failed_activation_is_not_repeated_by_timer(self, latest, deploy):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "deployment-status.json").write_text(json.dumps({
                "requestedSha": "a" * 40, "success": False, "phase": "activation_failed"}))
            self.assertEqual(poll(root, "/release", "1:A", "2026-11-23")["reason"], "previous_activation_failed")
            deploy.assert_not_called()
