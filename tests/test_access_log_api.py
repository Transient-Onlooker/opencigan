import json
import unittest
from datetime import datetime, timedelta
from unittest.mock import Mock, patch

from backend.app import dispatch_request
from backend.access_logs import AccessLogRecorder, AccessLogStore, SEOUL
from backend.cache import Cache


class AccessLogApiTests(unittest.TestCase):
    def test_school_usage_aggregates_typed_valid_ids_without_personal_fields(self):
        store = AccessLogStore(':memory:', retention_days=7)
        self.addCleanup(store.close)
        now = datetime.now(SEOUL)
        events = [
            ('timetable', '1234:Example High', '203.0.113.1', now),
            ('timetable', '1234:Example High', '203.0.113.2', now - timedelta(days=1)),
            ('meals', 'B10:1234567', '203.0.113.3', now),
            ('meals', '1234:Example High', '203.0.113.4', now),
            ('timetable', 'invalid', '203.0.113.5', now),
            ('other', '9999:Other', '203.0.113.6', now),
        ]
        for datatype, school_id, ip, received_at in events:
            store.record({
                'datatype': datatype, 'school_id': school_id, 'client_ip': ip,
                'route': '/api/v1/timetable', 'status': 200, 'cache_status': 'hit',
                'grade': '2', 'class_nm': '3',
            }, received_at=received_at)

        with patch('backend.app._access_log_store', return_value=store), patch.dict(
            'os.environ', {'OPENCIGAN_ADMIN_TOKEN': 'test-secret'}
        ):
            status, headers, body = dispatch_request(
                'GET', '/api/v1/admin/school-usage', 'days=2&limit=10',
                request_headers={'Authorization': 'Bearer test-secret'},
            )
        payload = json.loads(body)
        self.assertEqual(status, 200)
        self.assertEqual(headers['Cache-Control'], 'no-store')
        self.assertEqual(payload['period_days'], 2)
        self.assertEqual(payload['items'], [
            {'datatype': 'timetable', 'school_id': '1234:Example High', 'school_name': None, 'requests': 2},
            {'datatype': 'meals', 'school_id': 'B10:1234567', 'school_name': None, 'requests': 1},
        ])
        serialized = json.dumps(payload)
        for private_value in ('203.0.113.', 'grade', 'class_nm'):
            self.assertNotIn(private_value, serialized)

    def test_school_usage_names_match_fresh_cache_ids_and_leave_conflicts_unresolved(self):
        store = AccessLogStore(':memory:', retention_days=7)
        self.addCleanup(store.close)
        for datatype, school_id in (
            ('timetable', '1234:Example High'),
            ('timetable', '5678:Example High'),
            ('meals', 'B10:1234567'),
        ):
            store.record({'datatype': datatype, 'school_id': school_id})

        cache = Cache()
        cache.get(('school_search', 'Example'), lambda: {'schools': [
            {'id': '1234:Example High', 'name': 'Example High', 'region': 'Region'},
            {'id': '5678:Example High', 'name': 'Example High', 'region': 'Region'},
        ], 'stale': False})
        cache.get(('neis_school_search', 'Example'), lambda: {'schools': [
            {'id': 'B10:1234567', 'name': 'NEIS Name', 'region': 'High', 'address': 'Address'},
        ], 'stale': False})
        cache.get(('neis_school_search', 'Other query'), lambda: {'schools': [
            {'id': 'B10:1234567', 'name': 'Conflicting Name', 'region': 'High', 'address': 'Address'},
        ], 'stale': False})

        with patch.dict('os.environ', {'OPENCIGAN_ADMIN_TOKEN': 'test-secret'}), patch(
            'backend.app._access_log_store', return_value=store
        ):
            status, _, body = dispatch_request(
                'GET', '/api/v1/admin/school-usage', '', cache_instance=cache,
                request_headers={'Authorization': 'Bearer test-secret'},
            )

        items = json.loads(body)['items']
        self.assertEqual(status, 200)
        self.assertEqual({(item['datatype'], item['school_id']): item['school_name'] for item in items}, {
            ('timetable', '1234:Example High'): 'Example High',
            ('timetable', '5678:Example High'): 'Example High',
            ('meals', 'B10:1234567'): None,
        })

    def test_school_usage_ignores_expired_school_search_cache_entries(self):
        store = AccessLogStore(':memory:', retention_days=7)
        self.addCleanup(store.close)
        store.record({'datatype': 'timetable', 'school_id': '1234:Example High'})
        cache = Cache(ttl=1)
        cache.get(('school_search', 'Example'), lambda: {'schools': [
            {'id': '1234:Example High', 'name': 'Example High', 'region': 'Region'},
        ], 'stale': False})
        with patch('backend.cache.time.monotonic', return_value=10**12), patch.dict(
            'os.environ', {'OPENCIGAN_ADMIN_TOKEN': 'test-secret'}
        ), patch('backend.app._access_log_store', return_value=store):
            status, _, body = dispatch_request(
                'GET', '/api/v1/admin/school-usage', '', cache_instance=cache,
                request_headers={'Authorization': 'Bearer test-secret'},
            )
        self.assertEqual(status, 200)
        self.assertIsNone(json.loads(body)['items'][0]['school_name'])

    def test_school_usage_auth_limits_and_disabled_storage(self):
        store = AccessLogStore(':memory:', retention_days=7)
        self.addCleanup(store.close)
        with patch.dict('os.environ', {'OPENCIGAN_ADMIN_TOKEN': 'test-secret'}), patch(
            'backend.app._access_log_store', return_value=store
        ):
            auth = {'Authorization': 'Bearer test-secret'}
            self.assertEqual(dispatch_request('GET', '/api/v1/admin/school-usage', '')[0], 401)
            for query in ('days=8', 'days=0', 'limit=101', 'days=2&days=3', 'unknown=x'):
                with self.subTest(query=query):
                    self.assertEqual(dispatch_request('GET', '/api/v1/admin/school-usage', query, request_headers=auth)[0], 400)
        with patch.dict('os.environ', {'OPENCIGAN_ADMIN_TOKEN': 'test-secret'}), patch(
            'backend.app._access_log_store', return_value=None
        ):
            self.assertEqual(dispatch_request('GET', '/api/v1/admin/school-usage', '', request_headers=auth)[0], 503)

    def test_school_usage_limit_counts_only_exactly_valid_ids(self):
        store = AccessLogStore(':memory:', retention_days=7)
        self.addCleanup(store.close)
        for school_id, count in (
            ('1:Highest', 3), ('2:Next', 2),
            *((f'{code}:Invalid\x01Name', 5) for code in range(10, 20)),
        ):
            for _ in range(count):
                store.record({'datatype': 'timetable', 'school_id': school_id})

        result = store.school_usage(7, limit=1)
        self.assertEqual(result['items'], [
            {'datatype': 'timetable', 'school_id': '1:Highest', 'school_name': None, 'requests': 3},
        ])
        self.assertTrue(result['has_more'])
        limited = store.school_usage(7, limit=2)
        self.assertEqual([item['school_id'] for item in limited['items']], ['1:Highest', '2:Next'])
        self.assertFalse(limited['has_more'])

    def test_common_admin_rate_limit_includes_suggestion_routes(self):
        with patch('backend.app._rate_allowed', return_value=12) as rate:
            for path in ('/api/v1/admin/suggestions', '/api/v1/admin/suggestions/abcdefghijklmnopqrstuvwx',
                         '/api/v1/admin/school-usage'):
                status, headers, _ = dispatch_request('GET', path, '', client='203.0.113.9')
                self.assertEqual(status, 429)
                self.assertEqual(headers['Retry-After'], '12')
            self.assertEqual(rate.call_args_list[0].args[0], ('admin', '203.0.113.9'))

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
