import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from deploy.release_deploy import deploy


@unittest.skipIf(os.name == "nt", "requires Linux file locking")
class ReleaseDeployTests(unittest.TestCase):
    @patch("deploy.release_deploy.installed_sha", return_value="a" * 40)
    @patch("deploy.release_deploy.prepare", side_effect=RuntimeError("offline"))
    def test_failed_new_candidate_preserves_previous_pending_pin(self, prepare, installed):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            status = root / "deployment-status.json"
            status.write_text(json.dumps({"activeSha": "a" * 40, "success": True, "pinSync": "failed",
                                          "verification": {"internal": True, "public": True}}))
            with self.assertRaisesRegex(RuntimeError, "offline"):
                deploy("1.4.7", "b" * 40, root, "/release", "1:A", "2026-11-23")
            result = json.loads(status.read_text())
            self.assertEqual(result["activeSha"], "a" * 40)
            self.assertEqual(result["pinSync"], "failed")
            self.assertEqual(result["lastAttempt"]["phase"], "prepare_failed")
    @patch("deploy.release_deploy.activate", return_value={"success": True})
    @patch("deploy.release_deploy.prepare")
    def test_existing_inactive_candidate_is_retested_before_activation(self, prepare, activate):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / ("a" * 40)).mkdir()
            result = deploy("1.4.6", "a" * 40, root, "/release", "1:A", "2026-11-23")
            self.assertTrue(result["success"])
            self.assertNotEqual(Path(prepare.call_args.args[2]), root)
            activate.assert_called_once()

    @patch("deploy.release_deploy.activate")
    @patch("deploy.release_deploy.prepare")
    @patch("deploy.release_deploy.installed_sha", return_value="a" * 40)
    def test_verified_same_sha_is_skipped_without_service_restart(self, installed, prepare, activate):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "deployment-status.json").write_text(json.dumps({
                "activeSha": "a" * 40, "success": True, "pinSync": "synced",
                "verification": {"internal": True, "public": True}}))
            result = deploy("1.4.6", "a" * 40, root, "/release", "1:A", "2026-11-23")
            self.assertTrue(result["skipped"])
            prepare.assert_not_called()
            activate.assert_not_called()

    @patch("deploy.release_deploy.retry_pin", return_value={"pinSync": "synced"})
    @patch("deploy.release_deploy.activate")
    @patch("deploy.release_deploy.prepare")
    @patch("deploy.release_deploy.installed_sha", return_value="a" * 40)
    def test_same_sha_retries_only_failed_pin(self, installed, prepare, activate, retry):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "deployment-status.json").write_text(json.dumps({
                "activeSha": "a" * 40, "success": True, "pinSync": "failed",
                "verification": {"internal": True, "public": True}}))
            self.assertEqual(deploy("1.4.6", "a" * 40, root, "/release", "1:A", "2026-11-23"), {"pinSync": "synced"})
            retry.assert_called_once()
            prepare.assert_not_called()
            activate.assert_not_called()

    @patch("deploy.release_deploy.activate")
    @patch("deploy.release_deploy.installed_sha", return_value="b" * 40)
    @patch("deploy.release_deploy.prepare", side_effect=RuntimeError("probe failed"))
    def test_prepare_failure_records_active_version_and_does_not_activate(self, prepare, installed_sha, activate):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "components"
            with self.assertRaisesRegex(RuntimeError, "probe failed"):
                deploy("1.4.6", "a" * 40, root, "/release", "1:A", "2026-11-23")
            status = json.loads((root / "deployment-status.json").read_text())
            self.assertEqual(status["requestedSha"], "a" * 40)
            self.assertEqual(status["activeSha"], "b" * 40)
            self.assertFalse(status["success"])
            self.assertEqual(status["phase"], "prepare_failed")
            activate.assert_not_called()
