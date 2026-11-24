import unittest
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from deploy.sync_pin import replace_pin, sync


class PinSyncTests(unittest.TestCase):
    def test_only_single_fork_pin_changes_and_line_endings_remain(self):
        source = ("# preserved\r\npycomcigan @ git+https://github.com/Transient-Onlooker/pycomcigan.git@"
                  + "a" * 40 + "\r\nrequests>=2.32.0\r\n")
        result = replace_pin(source, "b" * 40)
        self.assertEqual(result, source.replace("a" * 40, "b" * 40))

    def test_rejects_ambiguous_pin_or_invalid_sha(self):
        line = "pycomcigan @ git+https://github.com/Transient-Onlooker/pycomcigan.git@" + "a" * 40
        for content, sha in ((line + "\n" + line, "b" * 40), (line, "bad"), ("requests>=2", "b" * 40)):
            with self.subTest(content=content, sha=sha), self.assertRaises(ValueError):
                replace_pin(content, sha)

    @unittest.skipIf(os.name == "nt", "requires Unix file permissions")
    @patch("deploy.sync_pin.subprocess.run")
    def test_dry_run_never_commits_or_pushes(self, run):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            key = root / "key"
            key.touch(mode=0o600)
            key.with_name("opencigan-github-known-hosts").touch(mode=0o600)
            def clone(command, **kwargs):
                checkout = Path(command[-1])
                (checkout / "backend").mkdir(parents=True)
                (checkout / "backend/requirements.txt").write_text(
                    "pycomcigan @ git+https://github.com/Transient-Onlooker/pycomcigan.git@" + "a" * 40 + "\n")
            run.side_effect = clone
            self.assertEqual(sync("b" * 40, key, dry_run=True), "would_sync")
            self.assertEqual(run.call_count, 1)
