import os
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch
from urllib.error import URLError

from backend import comcigan_proxy


# Integration layer: unlike the proxy unit tests, this test intentionally
# enters through pycomcigan's own call path, so it verifies that the
# library actually routes through the configured proxy with its default
# timeout. A change in the library's internal call surface is supposed
# to surface here; the proxy unit tests must not depend on it.
@unittest.skipUnless(os.environ.get('OPENCIGAN_SLOW_NETWORK_TESTS') == '1', 'opt-in 30-second socket test')
class RealProxyTimeoutTests(unittest.TestCase):
    def test_default_post_timeout_against_unresponsive_local_proxy(self):
        import pycomcigan.helpers as helpers

        release = threading.Event()
        started = threading.Event()

        class SlowProxy(BaseHTTPRequestHandler):
            def do_POST(self):
                started.set()
                release.wait(40)

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(('127.0.0.1', 0), SlowProxy)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            proxy = f'http://127.0.0.1:{server.server_port}'
            with patch.dict('os.environ', {'OPENCIGAN_COMCIGAN_PROXY': proxy}), \
                 patch.object(helpers, 'urlopen', helpers.urlopen), \
                 patch.object(comcigan_proxy, '_configured', False):
                comcigan_proxy.configure_comcigan_proxy()
                started_at = time.monotonic()
                with self.assertLogs('opensigan.comcigan_proxy', level='INFO') as logs:
                    with self.assertRaises((TimeoutError, URLError)):
                        helpers.get_response_encoding('http://comci.net:4082/12345', 'UTF-8',
                                                      request_token='test-token', body=b'test-body')
                elapsed = time.monotonic() - started_at
            self.assertTrue(started.is_set())
            self.assertGreaterEqual(elapsed, 29)
            self.assertLess(elapsed, 40)
            self.assertIn('result=timeout timeout_s=30', logs.output[0])
            self.assertNotIn('test-token', logs.output[0])
            self.assertNotIn('test-body', logs.output[0])
        finally:
            release.set()
            server.shutdown()
            server.server_close()
            thread.join()
