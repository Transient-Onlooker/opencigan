import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from deploy.activate_component import _activate, retry_pin


@unittest.skipIf(os.name == "nt", "requires Linux symlink semantics")
class ActivateComponentTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.home = Path(self.temporary.name)
        self.root = self.home / "components"
        self.sha = "a" * 40
        self.package = self.root / self.sha / "pycomcigan"
        self.package.mkdir(parents=True)
        data = b"package\n"
        (self.package / "__init__.py").write_bytes(data)
        self.manifest = {"repo": "Transient-Onlooker/pycomcigan", "tag": "1.4.6", "version": "1.4.6", "git_sha": self.sha,
                         "origin": "upstream", "files": {"__init__.py": hashlib.sha256(data).hexdigest()}}
        (self.package.parent / "deploy-manifest.json").write_text(json.dumps(self.manifest))
        info = self.package.parent / "pycomcigan-1.4.6.dist-info"
        info.mkdir()
        (info / "METADATA").write_text("Metadata-Version: 2.1\nName: pycomcigan\nVersion: 1.4.6\nRequires-Dist: pycryptodomex>=3.23,<4\n")
        (info / "direct_url.json").write_text(json.dumps({"url": "https://github.com/Transient-Onlooker/pycomcigan.git", "vcs_info": {"vcs": "git", "commit_id": self.sha, "requested_revision": self.sha}}))
        token = self.home / ".config/opencigan/internal.env"
        token.parent.mkdir(parents=True)
        token.write_text("OPENCIGAN_INTERNAL_TOKEN=test-secret\n")
        key = self.home / ".ssh/opencigan-pin-sync"
        key.parent.mkdir(parents=True)
        key.touch(mode=0o600)
        key.with_name("opencigan-github-known-hosts").touch(mode=0o600)
        metadata = {"url": "https://github.com/Transient-Onlooker/pycomcigan.git", "vcs_info": {"commit_id": "b" * 40}}
        direct = patch("deploy.activate_component.subprocess.check_output", return_value=json.dumps(metadata))
        direct.start()
        self.addCleanup(direct.stop)
        sync = patch("deploy.activate_component.sync", return_value="synced")
        sync.start()
        self.addCleanup(sync.stop)

    @patch("deploy.activate_component.wait_ready")
    @patch("deploy.activate_component.probe")
    @patch("deploy.activate_component.systemctl")
    @patch("deploy.activate_component.load_release")
    def test_success_restarts_internal_before_public(self, load, systemctl, probe, ready):
        load.return_value = self.manifest
        with patch("deploy.activate_component.Path.home", return_value=self.home):
            state = _activate("1.4.6", self.sha, self.root, "1:A", "2026-11-23")
        self.assertTrue(state["success"])
        self.assertEqual((self.root / "current").resolve(), self.root / self.sha)
        self.assertEqual([call.args for call in systemctl.call_args_list], [
            ("daemon-reload",), ("restart", "opencigan-internal.service"), ("restart", "opensigan.service")])
        self.assertEqual(json.loads((self.root / "deployment-status.json").read_text())["activeSha"], self.sha)

    @patch("deploy.activate_component.wait_ready")
    @patch("deploy.activate_component.probe")
    @patch("deploy.activate_component.systemctl")
    @patch("deploy.activate_component.load_release")
    def test_failed_public_probe_restores_both_services(self, load, systemctl, probe, ready):
        load.return_value = self.manifest
        probe.side_effect = [None, RuntimeError("public probe failed"), None, None]
        with patch("deploy.activate_component.Path.home", return_value=self.home):
            with self.assertRaisesRegex(RuntimeError, "public probe failed"):
                _activate("1.4.6", self.sha, self.root, "1:A", "2026-11-23")
        self.assertFalse((self.root / "current").is_symlink())
        state = json.loads((self.root / "deployment-status.json").read_text())
        self.assertFalse(state["success"])
        self.assertTrue(state["rollback"])
        self.assertEqual([call.args for call in systemctl.call_args_list][-2:], [
            ("restart", "opencigan-internal.service"), ("restart", "opensigan.service")])

    @patch("deploy.activate_component.sync", side_effect=RuntimeError("synchronization failed"))
    @patch("deploy.activate_component.wait_ready")
    @patch("deploy.activate_component.probe")
    @patch("deploy.activate_component.systemctl")
    @patch("deploy.activate_component.load_release")
    def test_sync_failure_is_recorded_without_undoing_verified_deployment(self, load, systemctl, probe, ready, sync):
        load.return_value = self.manifest
        with patch("deploy.activate_component.Path.home", return_value=self.home):
            with self.assertRaisesRegex(RuntimeError, "synchronization failed"):
                _activate("1.4.6", self.sha, self.root, "1:A", "2026-11-23")
        state = json.loads((self.root / "deployment-status.json").read_text())
        self.assertTrue(state["success"])
        self.assertEqual(state["pinSync"], "failed")
        self.assertEqual(state["phase"], "pin_sync_failed")
        self.assertEqual((self.root / "current").resolve(), self.root / self.sha)

    @patch("deploy.activate_component.wait_ready")
    @patch("deploy.activate_component.probe", side_effect=[RuntimeError("internal probe failed"), None, None])
    @patch("deploy.activate_component.systemctl")
    @patch("deploy.activate_component.load_release")
    def test_failure_restores_previous_component_and_dropins(self, load, systemctl, probe, ready):
        load.return_value = self.manifest
        previous = self.root / ("c" * 40)
        previous.mkdir()
        (self.root / "current").symlink_to(previous)
        existing = self.home / ".config/systemd/user/opensigan.service.d/10-pycomcigan.conf"
        existing.parent.mkdir(parents=True)
        existing.write_text("previous settings\n")
        with patch("deploy.activate_component.Path.home", return_value=self.home):
            with self.assertRaisesRegex(RuntimeError, "internal probe failed"):
                _activate("1.4.6", self.sha, self.root, "1:A", "2026-11-23")
        self.assertEqual((self.root / "current").resolve(), previous)
        self.assertEqual(existing.read_text(), "previous settings\n")
        state = json.loads((self.root / "deployment-status.json").read_text())
        self.assertEqual(state["activeSha"], "c" * 40)
        self.assertTrue(state["rollback"])

    @patch("deploy.activate_component.sync", return_value="synced")
    def test_pin_retry_requires_verified_active_component(self, sync):
        (self.root / "current").symlink_to(self.package.parent)
        state_path = self.root / "deployment-status.json"
        state_path.write_text(json.dumps({"activeSha": self.sha, "success": True,
                                          "verification": {"internal": True, "public": True}}))
        with patch("deploy.activate_component.Path.home", return_value=self.home):
            state = retry_pin(self.root)
        self.assertEqual(state["pinSync"], "synced")
        state_path.write_text(json.dumps({"activeSha": self.sha, "success": False}))
        with self.assertRaisesRegex(ValueError, "not verified"):
            retry_pin(self.root)

    @patch("deploy.activate_component.wait_ready")
    @patch("deploy.activate_component.probe", side_effect=[RuntimeError("initial failure"), None, None])
    @patch("deploy.activate_component.systemctl", side_effect=[None, None, RuntimeError("reload failure"), None, None])
    @patch("deploy.activate_component.load_release")
    def test_partial_rollback_error_is_recorded_and_public_restart_attempted(self, load, systemctl, probe, ready):
        load.return_value = self.manifest
        with patch("deploy.activate_component.Path.home", return_value=self.home):
            with self.assertRaisesRegex(RuntimeError, "initial failure"):
                _activate("1.4.6", self.sha, self.root, "1:A", "2026-11-23")
        state = json.loads((self.root / "deployment-status.json").read_text())
        self.assertFalse(state["rollback"])
        self.assertEqual(state["rollbackErrors"], ["RuntimeError"])
        self.assertEqual(systemctl.call_args_list[-1].args, ("restart", "opensigan.service"))
