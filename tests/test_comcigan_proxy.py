import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError
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

    def test_header_timing_records_only_stage_and_duration_on_success_and_failure(self):
        import pycomcigan.helpers as helpers
        original = helpers.urlopen
        self.addCleanup(setattr, helpers, "urlopen", original)
        opener = Mock()
        with patch.dict("os.environ", {"OPENCIGAN_COMCIGAN_PROXY": "http://127.0.0.1:18084"}), \
             patch.object(comcigan_proxy, "build_opener", return_value=opener), \
             patch.object(comcigan_proxy.time, "monotonic", side_effect=[10.0, 10.25, 20.0, 20.5]):
            comcigan_proxy.configure_comcigan_proxy()
            with self.assertLogs("opensigan.comcigan_proxy", level="INFO") as logs:
                helpers.urlopen(Request("http://comci.net:4082/st?private=secret"))
                opener.open.side_effect = TimeoutError("private details")
                with self.assertRaises(TimeoutError):
                    helpers.urlopen(Request("http://comci.net:4082/private?school=secret"))
            self.assertIn("stage=service_page duration_ms=250.0", logs.output[0])
            self.assertIn("stage=data duration_ms=500.0", logs.output[1])
            self.assertEqual(opener.open.call_args.kwargs['timeout'], 30)
            for line in logs.output:
                for private in ("secret", "school", "comci.net", "private details"):
                    self.assertNotIn(private, line)

    def test_rejection_status_logged_without_request_details(self):
        import pycomcigan.helpers as helpers
        original = helpers.urlopen
        self.addCleanup(setattr, helpers, "urlopen", original)
        opener = Mock()
        with patch.dict("os.environ", {"OPENCIGAN_COMCIGAN_PROXY": "http://127.0.0.1:18084"}), \
             patch.object(comcigan_proxy, "build_opener", return_value=opener):
            comcigan_proxy.configure_comcigan_proxy()
            for status in (403, 429):
                with self.subTest(status=status):
                    error = HTTPError("http://comci.net:4082/?secret=token", status, "private message", {}, None)
                    self.addCleanup(error.close)
                    opener.open.side_effect = error
                    with self.assertLogs("opensigan.comcigan_proxy", level="WARNING") as logs:
                        with self.assertRaises(HTTPError) as raised:
                            helpers.urlopen(Request("http://comci.net:4082/?secret=token"))
                    self.assertIs(raised.exception, error)
                    self.assertIn(f"upstream_http_status={status}", logs.output[0])
                    for private in ("secret", "token", "private message", "comci.net"):
                        self.assertNotIn(private, logs.output[0])

    def test_disabled_does_not_change_urllib(self):
        import pycomcigan.helpers as helpers
        original = helpers.urlopen
        with patch.dict("os.environ", {"OPENCIGAN_COMCIGAN_PROXY": ""}):
            comcigan_proxy.configure_comcigan_proxy()
        self.assertIs(helpers.urlopen, original)
