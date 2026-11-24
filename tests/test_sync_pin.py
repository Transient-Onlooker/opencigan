import unittest

from deploy.sync_pin import replace_pin


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
