import unittest
from unittest.mock import Mock, patch
from urllib.request import Request

from backend import comcigan_proxy


class ComciganProxyTests(unittest.TestCase):
    def setUp(self):
        self.original_configured = comcigan_proxy._configured
        comcigan_proxy._configured = False
        self.addCleanup(setattr, comcigan_proxy, "_configured", self.original_configured)

    def test_proxy_is_scoped_to_comcigan_and_never_falls_back(self):
        import pycomcigan.helpers as helpers
        original = helpers.urlopen
        self.addCleanup(setattr, helpers, "urlopen", original)
        opener = Mock()
        opener.open.side_effect = OSError("proxy down")
        with patch.dict("os.environ", {"OPENCIGAN_COMCIGAN_PROXY": "http://127.0.0.1:18084", "no_proxy": "comci.net"}), \
             patch.object(comcigan_proxy, "build_opener", return_value=opener):
            comcigan_proxy.configure_comcigan_proxy()
            with self.assertRaisesRegex(OSError, "proxy down"):
                helpers.urlopen(Request("http://comci.net:4082/st"), timeout=30)
            opener.open.assert_called_once()
            self.assertEqual(opener.open.call_args.args[0].host, "127.0.0.1:18084")
            with self.assertRaises(ValueError):
                helpers.urlopen(Request("http://example.org/"))

    def test_remote_proxy_is_rejected(self):
        with patch.dict("os.environ", {"OPENCIGAN_COMCIGAN_PROXY": "http://example.org:8080"}):
            with self.assertRaises(ValueError):
                comcigan_proxy.configure_comcigan_proxy()

    def test_disabled_does_not_change_urllib(self):
        import pycomcigan.helpers as helpers
        original = helpers.urlopen
        with patch.dict("os.environ", {"OPENCIGAN_COMCIGAN_PROXY": ""}):
            comcigan_proxy.configure_comcigan_proxy()
        self.assertIs(helpers.urlopen, original)
