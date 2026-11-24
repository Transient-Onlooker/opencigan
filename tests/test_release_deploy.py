import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from deploy.release_deploy import deploy


@unittest.skipIf(os.name == "nt", "requires Linux file locking")
class ReleaseDeployTests(unittest.TestCase):
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
