import json
import hashlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from deploy.release_deploy import deploy


def active_component(root, sha, version):
    component = root / sha
    package = component / "pycomcigan"
    package.mkdir(parents=True)
    content = b"# fixture\n"
    (package / "__init__.py").write_bytes(content)
    (component / "deploy-manifest.json").write_text(json.dumps({
        "name": "pycomcigan", "version": version, "git_sha": sha,
        "origin": "upstream", "files": {"pycomcigan/__init__.py": hashlib.sha256(content).hexdigest()}}))
    info = component / ("pycomcigan-" + version + ".dist-info")
    info.mkdir()
    (info / "METADATA").write_text("Metadata-Version: 2.1\nName: pycomcigan\nVersion: " + version +
                                   "\nRequires-Dist: pycryptodomex>=3.23,<4\n")
    (info / "direct_url.json").write_text(json.dumps({"url": "https://github.com/Transient-Onlooker/pycomcigan.git",
                                                       "vcs_info": {"commit_id": sha}}))
    return component


@unittest.skipIf(os.name == "nt", "requires Linux file locking")
class ReleaseDeployTests(unittest.TestCase):
    @patch("deploy.release_deploy.installed_sha", return_value="a" * 40)
    def test_automatic_guard_rejects_tampered_active_package(self, installed):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            component = active_component(root, "a" * 40, "1.4.9")
            (component / "pycomcigan" / "__init__.py").write_text("changed")
            (root / "deployment-status.json").write_text(json.dumps({"activeSha": "a" * 40, "success": True,
                "verification": {"internal": True, "public": True}}))
            with self.assertRaisesRegex(ValueError, "file hash mismatch"):
                deploy("1.4.8", "b" * 40, root, "/release", "1:A", "2026-11-23", automatic=True)

    @patch("deploy.release_deploy.retry_pin", return_value={"pinSync": "synced"})
    @patch("deploy.release_deploy.load_release", return_value={"version": "1.4.8"})
    def test_deleted_latest_release_cannot_downgrade_active_component_or_block_pin_retry(self, load, retry):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            sha = "a" * 40
            component = active_component(root, sha, "1.4.9")
            (root / "current").symlink_to(component)
            status = {"activeSha": sha, "success": True, "pinSync": "failed",
                      "verification": {"internal": True, "public": True}}
            (root / "deployment-status.json").write_text(json.dumps(status))
            self.assertEqual(deploy("1.4.8", "b" * 40, root, "/release", "1:A", "2026-11-23", automatic=True),
                             {"pinSync": "synced"})
            self.assertEqual((root / "current").resolve(), component)
            retry.assert_called_once_with(root)

    @patch("deploy.release_deploy.installed_sha", return_value="a" * 40)
    @patch("deploy.release_deploy.prepare", side_effect=RuntimeError("offline"))
    def test_failed_preparation_keeps_verified_active_state_for_future_auto_recovery(self, prepare, installed):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            status = root / "deployment-status.json"
            status.write_text(json.dumps({"activeSha": "a" * 40, "success": True, "pinSync": "synced",
                                          "verification": {"internal": True, "public": True}}))
            with self.assertRaisesRegex(RuntimeError, "offline"):
                deploy("1.4.10", "b" * 40, root, "/release", "1:A", "2026-11-23")
            state = json.loads(status.read_text())
            self.assertTrue(state["success"])
            self.assertEqual(state["activeSha"], "a" * 40)
            self.assertEqual(state["lastAttempt"]["phase"], "prepare_failed")

    @patch("deploy.release_deploy.activate", return_value={"success": True})
    @patch("deploy.release_deploy.prepare")
    @patch("deploy.release_deploy.load_release")
    @patch("deploy.release_deploy.installed_sha", return_value="a" * 40)
    def test_automatic_version_policy(self, installed, load, prepare, activate):
        cases = [
            ("1.4.8+autofix.1", "1.4.9", "deploy"),
            ("1.4.9", "1.4.8", "older_release"),
            ("1.4.9", "1.4.8+autofix.1", "older_release"),
            ("1.4.9", "1.4.9+autofix.1", "deploy"),
            ("1.4.9+autofix.1", "1.4.9+autofix.2", "deploy"),
            ("1.4.9", "1.4.9", "version_sha_mismatch"),
        ]
        for active, candidate, expected in cases:
            with self.subTest(active=active, candidate=candidate), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                active_component(root, "a" * 40, active)
                (root / "deployment-status.json").write_text(json.dumps({
                    "activeSha": "a" * 40, "success": True, "pinSync": "synced",
                    "verification": {"internal": True, "public": True}}))
                load.return_value = {"version": candidate}
                prepare.reset_mock()
                activate.reset_mock()
                result = deploy(candidate, "b" * 40, root, "/release", "1:A", "2026-11-23", automatic=True)
                if expected == "deploy":
                    self.assertTrue(result["success"])
                    prepare.assert_called_once()
                    activate.assert_called_once()
                else:
                    self.assertEqual(result["reason"], expected)
                    prepare.assert_not_called()
                    activate.assert_not_called()

    @patch("deploy.release_deploy.activate", return_value={"success": True})
    @patch("deploy.release_deploy.prepare")
    def test_explicit_rollback_does_not_apply_automatic_guard(self, prepare, activate):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "deployment-status.json").write_text(json.dumps({"activeSha": "b" * 40, "success": True}))
            self.assertTrue(deploy("1.4.8", "a" * 40, root, "/release", "1:A", "2026-11-23")["success"])
            activate.assert_called_once()

    @patch("deploy.release_deploy.installed_sha", return_value="a" * 40)
    def test_automatic_deployment_rejects_unverified_active_state(self, installed):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "deployment-status.json").write_text(json.dumps({"activeSha": "b" * 40, "success": True,
                "verification": {"internal": True, "public": True}}))
            with self.assertRaisesRegex(ValueError, "not verified"):
                deploy("1.4.9", "b" * 40, root, "/release", "1:A", "2026-11-23", automatic=True)
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
