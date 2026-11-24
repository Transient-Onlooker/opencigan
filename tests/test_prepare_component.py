import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from deploy.prepare_component import prepare


class PrepareComponentTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.release = self.root / "release"
        python = self.release / ".venv/bin/python"
        python.parent.mkdir(parents=True)
        python.touch()
        self.sha = "a" * 40
        self.content = b"verified\n"
        self.manifest = {"repo": "Transient-Onlooker/pycomcigan", "tag": "1.4.6", "version": "1.4.6",
                         "git_sha": self.sha, "origin": "upstream", "dependencies": {"pycryptodomex": ">=3.23,<4"},
                         "files": {"__init__.py": hashlib.sha256(self.content).hexdigest()}}

    @patch("deploy.prepare_component.load_release")
    def test_existing_component_is_not_overwritten(self, load):
        load.return_value = self.manifest
        destination = self.root / "components" / self.sha
        destination.mkdir(parents=True)
        (destination / "sentinel").write_text("keep")
        with self.assertRaisesRegex(ValueError, "already exists"):
            prepare("1.4.6", self.sha, destination.parent, self.release, "1:A", "2026-11-23")
        self.assertEqual((destination / "sentinel").read_text(), "keep")

    @patch("deploy.prepare_component.subprocess.check_output")
    @patch("deploy.prepare_component.run")
    @patch("deploy.prepare_component.load_release")
    def test_failed_live_check_never_publishes_component(self, load, run, output):
        load.return_value = self.manifest
        output.return_value = self.sha
        def fake_run(command, **kwargs):
            if command[0] == "git" and command[1] == "clone":
                package = Path(command[-1]) / "pycomcigan"
                package.mkdir(parents=True)
                (package / "__init__.py").write_bytes(self.content)
            elif "-c" in command:
                raise RuntimeError("live check failed")
        run.side_effect = fake_run
        with self.assertRaisesRegex(RuntimeError, "live check failed"):
            prepare("1.4.6", self.sha, self.root / "components", self.release, "1:A", "2026-11-23")
        self.assertFalse((self.root / "components" / self.sha).exists())
