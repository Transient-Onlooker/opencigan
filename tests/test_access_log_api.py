import json
import unittest
from unittest.mock import Mock, patch

from backend.app import dispatch_request
from backend.access_logs import AccessLogRecorder, AccessLogStore


class AccessLogApiTests(unittest.TestCase):
    def test_admin_errors_include_standard_error_and_code(self):
        with patch.dict('os.environ', {'OPENCIGAN_ADMIN_TOKEN': 'test-secret'}), \
             patch('backend.app._access_log_store', return_value=None):
            for method, query, auth, expected in (
                ('GET', '', '', 401),
                ('POST', '', 'Bearer test-secret', 405),
                ('GET', 'limit=invalid', 'Bearer test-secret', 400),
                ('GET', '', 'Bearer test-secret', 503),
            ):
                with self.subTest(status=expected):
                    status, headers, body = dispatch_request(method, '/api/v1/admin/access-logs', query,
                                                             request_headers={'Authorization': auth})
                    self.assertEqual(status, expected)
                    self.assertEqual(int(headers['Content-Length']), len(body))
                    payload = json.loads(body)
                    self.assertIsInstance(payload['error'], str)
                    self.assertIsInstance(payload['code'], str)

    def test_recorded_request_round_trips_through_authenticated_query(self):
        store = AccessLogStore(':memory:')
        recorder = AccessLogRecorder(lambda: store)
        self.addCleanup(store.close)
        self.addCleanup(recorder.close)
        config = {'OPENCIGAN_ACCESS_LOG_DB': 'enabled', 'OPENCIGAN_ADMIN_TOKEN': 'test-secret'}
        with patch.dict('os.environ', config), patch('backend.app._access_log_recorder', recorder), patch('backend.app._access_log_store', return_value=store):
            with patch('backend.app._dispatch_request', return_value=(200, {'Content-Type': 'application/json'}, b'{"cacheStatus":"hit"}')):
                dispatch_request('GET', '/api/v1/timetable', 'school=2%3AExample&grade=2&class=3&week=2026-11-09&token=private', client='203.0.113.1', request_headers={'User-Agent': 'OpenCigan-Test/1.0'})
            self.assertTrue(recorder.flush(timeout=2))
            status, _, body = dispatch_request('GET', '/api/v1/admin/access-logs', 'grade=2&class=3', request_headers={'Authorization': 'Bearer test-secret'})
            self.assertEqual(status, 200)
            row = json.loads(body)['items'][0]
            self.assertEqual(row['school_id'], '2:Example')
            self.assertEqual(row['cache_status'], 'hit')
            self.assertEqual(row['user_agent'], 'OpenCigan-Test/1.0')
            self.assertEqual(row['week'], '2026-11-09')
            self.assertTrue(row['timestamp'].endswith('+09:00'))
            self.assertNotIn('private', json.dumps(row))

    def test_authentication_and_filters_and_csv(self):
        store = Mock()
        store.query.return_value = {'items': [], 'next_cursor': None}
        store.export_csv.return_value = 'timestamp,client_ip\r\n'
        with patch.dict('os.environ', {'OPENCIGAN_ADMIN_TOKEN': 'test-secret'}), patch('backend.app._access_log_store', return_value=store):
            for authorization in ['', 'Bearer wrong']:
                status, headers, _ = dispatch_request('GET', '/api/v1/admin/access-logs', '', request_headers={'Authorization': authorization})
                self.assertEqual(status, 401)
                self.assertEqual(headers['Cache-Control'], 'no-store')
            auth = {'Authorization': 'Bearer test-secret'}
            status, _, body = dispatch_request('GET', '/api/v1/admin/access-logs', 'client_ip=203.0.113.1&grade=2&class=3&start_day=2026-11-01&end_day=2026-11-15&limit=20', request_headers=auth)
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(body)['items'], [])
            store.query.assert_called_once_with({'client_ip': '203.0.113.1', 'grade': '2', 'class': '3', 'start_day': '2026-11-01', 'end_day': '2026-11-15'}, cursor=None, limit=20)
            status, headers, body = dispatch_request('GET', '/api/v1/admin/access-logs', 'format=csv', request_headers=auth)
            self.assertEqual(status, 200)
            self.assertTrue(body.startswith(b'\xef\xbb\xbf'))
            self.assertIn('text/csv', headers['Content-Type'])

    def test_invalid_admin_queries_and_disabled_storage(self):
        with patch.dict('os.environ', {'OPENCIGAN_ADMIN_TOKEN': 'test-secret'}), patch('backend.app._access_log_store', return_value=None):
            auth = {'Authorization': 'Bearer test-secret'}
            for query in ['limit=101', 'limit=x', 'cursor=-2', 'grade=7', 'status=999', 'class=100',
                          'start_day=2026-02-30', 'start_day=2026-11-15&end_day=2026-11-01',
                          'origin_class=trusted', 'q=secret', 'format=csv&format=json']:
                with self.subTest(query=query):
                    self.assertEqual(dispatch_request('GET', '/api/v1/admin/access-logs', query, request_headers=auth)[0], 400)
            self.assertEqual(dispatch_request('GET', '/api/v1/admin/access-logs', '', request_headers=auth)[0], 503)

    def test_only_allowed_fields_recorded_and_admin_requests_excluded(self):
        with patch.dict('os.environ', {'OPENCIGAN_ACCESS_LOG_DB': 'synthetic.sqlite', 'ALLOWED_ORIGIN': 'https://frontend.example'}), patch('backend.app._access_log_recorder') as recorder:
            dispatch_request('GET', '/api/v1/unknown/secret', 'q=private&token=sensitive&school=private&grade=sensitive&week=private', client='203.0.113.1', request_origin='https://frontend.example', request_headers={'Authorization': 'Bearer sensitive', 'Referer': 'https://frontend.example/meals?token=private'})
            event = recorder.submit.call_args[0][0]
            self.assertEqual(event['route'], '/unknown')
            self.assertEqual(event['client_ip'], '203.0.113.1')
            self.assertEqual(event['origin_class'], 'frontend')
            received_at = recorder.submit.call_args.kwargs['received_at']
            self.assertEqual(received_at.utcoffset().total_seconds(), 9 * 3600)
            self.assertNotIn('private', json.dumps(event))
            self.assertNotIn('sensitive', json.dumps(event))
            recorder.reset_mock()
            dispatch_request('GET', '/api/v1/admin/access-logs', '')
            recorder.submit.assert_not_called()

    def test_logging_off_by_default_does_not_submit(self):
        with patch.dict('os.environ', {'OPENCIGAN_ACCESS_LOG_DB': ''}), patch('backend.app._access_log_recorder') as recorder:
            dispatch_request('GET', '/api/v1/status', '')
            recorder.submit.assert_not_called()
