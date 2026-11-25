import json
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from backend.app import dispatch_request, _rate_clients
from backend.cache import Cache


class PublicApiTests(unittest.TestCase):
    def setUp(self):
        _rate_clients.clear()

    def test_filter_validation_uses_patchable_query_boundary(self):
        from backend.app import _timetable_filters
        with patch('backend.app._query_param', return_value='2') as query_value:
            self.assertEqual(_timetable_filters({'grade': ['ignored']}), (2, None, None))
        query_value.assert_called_once_with({'grade': ['ignored']}, 'grade', 1)

    def test_cors_restricts_origins_and_options_does_not_use_limit(self):
        with patch.dict('os.environ', {'ALLOWED_ORIGIN': 'https://example.test'}):
            for _ in range(65):
                status, headers, _ = dispatch_request('OPTIONS', '/api/v1/schools', '', client='x', request_origin='https://evil.test')
                self.assertEqual(status, 204)
                self.assertNotIn('Access-Control-Allow-Origin', headers)
            _, headers, _ = dispatch_request('OPTIONS', '/api/v1/schools', '', request_origin='https://example.test')
            self.assertEqual(headers['Access-Control-Allow-Origin'], 'https://example.test')

    def test_calendar_conditional_headers_are_available_to_allowed_origins(self):
        path = '/api/v1/timetable.ics'
        with patch.dict('os.environ', {'ALLOWED_ORIGIN': 'https://example.test'}):
            status, headers, _ = dispatch_request('OPTIONS', path, '', request_origin='https://example.test')
            self.assertEqual(status, 204)
            self.assertIn('If-None-Match', headers['Access-Control-Allow-Headers'])
            _, headers, _ = dispatch_request('GET', path, '', request_origin='https://example.test')
            self.assertIn('ETag', headers['Access-Control-Expose-Headers'])
            _, headers, _ = dispatch_request('GET', path, '', request_origin='https://other.test')
            self.assertNotIn('Access-Control-Expose-Headers', headers)

    def test_preflight_preserves_route_specific_methods_and_headers(self):
        with patch.dict('os.environ', {'ALLOWED_ORIGIN': 'https://first.test, https://second.test'}):
            status, headers, body = dispatch_request('OPTIONS', '/api/v1/webhooks/abc', '', request_origin='https://second.test')
            self.assertEqual((status, body), (204, b''))
            self.assertEqual(headers['Access-Control-Allow-Origin'], 'https://second.test')
            self.assertEqual(headers['Access-Control-Allow-Methods'], 'GET, HEAD, POST, PUT, DELETE, OPTIONS')
            self.assertEqual(headers['Content-Length'], '0')
            status, headers, body = dispatch_request('OPTIONS', '/api/v1/timetable/history.rss', '')
            self.assertEqual((status, body), (204, b''))
            self.assertEqual(headers['Access-Control-Allow-Origin'], 'https://first.test')
            self.assertEqual(headers['Access-Control-Expose-Headers'], 'Retry-After, ETag')
            self.assertIn('If-None-Match', headers['Access-Control-Allow-Headers'])

    def test_rate_limit_and_error_contract(self):
        for _ in range(60):
            status, _, _ = dispatch_request('GET', '/api/v1/schools', '', client='client')
            self.assertEqual(status, 400)
        status, headers, body = dispatch_request('GET', '/api/v1/schools', '', client='client')
        self.assertEqual(status, 429)
        self.assertGreater(int(headers['Retry-After']), 0)
        self.assertEqual(json.loads(body)['code'], 'rate_limited')
        self.assertEqual(dispatch_request('GET', '/api/v1/status', '', client='client')[0], 200)

    def test_timetable_cache_state_and_disabled_history(self):
        result = {'schoolId': '1:Example', 'weekStart': '2026-11-09', 'records': [], 'stale': False}
        with patch('backend.app.validate_timetable_week'), patch('backend.app.fetch_timetable', return_value=result) as fetch, patch.dict('os.environ', {'OPENCIGAN_HISTORY_DB': ''}):
            cache = Cache()
            query = 'school=1%3AExample&week=2026-11-09'
            first = json.loads(dispatch_request('GET', '/api/v1/timetable', query, cache)[2])
            second = json.loads(dispatch_request('GET', '/api/v1/timetable', query, cache)[2])
            self.assertEqual((first['cacheStatus'], second['cacheStatus']), ('miss', 'hit'))
            fetch.assert_called_once()
            status, _, body = dispatch_request('GET', '/api/v1/timetable/history', query)
            self.assertEqual((status, json.loads(body)['code']), (503, 'history_disabled'))

    def test_timetable_filters_reuse_school_cache_without_changing_full_result(self):
        records = [
            {'grade': 1, 'class': 2, 'date': '2026-11-09', 'period': 1, 'teacher': 'Kim'},
            {'grade': 1, 'class': '3', 'date': '2026-11-09', 'period': 1, 'teacher': None},
            {'grade': 2, 'class': 2, 'date': '2026-11-09', 'period': 1, 'teacher': 'Kim Min'},
        ]
        response = {'schoolId': '1:Example', 'weekStart': '2026-11-09', 'records': records,
                    'fetchedAt': '2026-11-09T00:00:00+00:00', 'stale': False}
        query = 'school=1%3AExample&week=2026-11-09'
        with patch('backend.app.validate_timetable_week'), patch('backend.app.fetch_timetable', return_value=response) as fetch, \
                patch.dict('os.environ', {'OPENCIGAN_HISTORY_DB': ''}):
            current_cache = Cache()
            filtered = json.loads(dispatch_request('GET', '/api/v1/timetable',
                                                 query + '&grade=1&class=2&teacher=kIM', current_cache)[2])
            self.assertEqual(filtered['records'], [records[0]])
            self.assertEqual(filtered['cacheStatus'], 'miss')
            school = json.loads(dispatch_request('GET', '/api/v1/timetable', query, current_cache)[2])
            self.assertEqual(school['records'], records)
            self.assertEqual(school['cacheStatus'], 'hit')
            by_class = json.loads(dispatch_request('GET', '/api/v1/timetable', query + '&class=3', current_cache)[2])
            self.assertEqual(by_class['records'], [records[1]])
            fetch.assert_called_once()

    def test_timetable_filters_reject_invalid_and_duplicate_inputs(self):
        query = 'school=1%3AExample&week=2026-11-09'
        with patch('backend.app.validate_timetable_week'), patch('backend.app.fetch_timetable') as fetch:
            for invalid in ('grade=0', 'grade=7', 'grade=1&grade=2', 'class=00',
                            'class=100', 'class=1.5', 'teacher=%20', 'teacher=A&teacher=B'):
                with self.subTest(invalid=invalid):
                    status, _, body = dispatch_request('GET', '/api/v1/timetable', query + '&' + invalid)
                    self.assertEqual((status, json.loads(body)['code']), (400, 'invalid_request'))
            fetch.assert_not_called()

    def test_ical_subscription_uses_shared_cache_and_valid_calendar_encoding(self):
        today = datetime.now(timezone(timedelta(hours=9))).date()
        start = today - timedelta(days=today.weekday())
        source = {'subject': '과학, 실험;\n준비', 'teacher': '김선생님', 'isChanged': True}

        def fake_fetch(school, week):
            return {
                'schoolId': school, 'weekStart': week, 'stale': False,
                'fetchedAt': '2026-11-14T00:00:00Z', 'sourceUpdatedAt': None,
                'records': [
                    {'grade': 2, 'class': 3, 'date': week, 'period': 1, **source},
                    {'grade': 2, 'class': 4, 'date': week, 'period': 2, 'subject': '체육', 'teacher': 'A'},
                ],
            }

        with patch('backend.app.fetch_timetable', side_effect=fake_fetch) as fetch, \
                patch.dict('os.environ', {'OPENCIGAN_HISTORY_DB': ''}):
            cache = Cache()
            query = 'school=2%3AExample&grade=2&class=3&weeks=2'
            status, headers, body = dispatch_request('GET', '/api/v1/timetable.ics', query, cache)
            self.assertEqual(status, 200)
            self.assertEqual(headers['Content-Type'], 'text/calendar; charset=utf-8')
            self.assertEqual(headers['Content-Length'], str(len(body)))
            self.assertTrue(body.startswith(b'BEGIN:VCALENDAR\r\n'))
            self.assertTrue(body.endswith(b'END:VCALENDAR\r\n'))
            self.assertTrue(all(len(line) <= 75 for line in body.split(b'\r\n')))
            self.assertIn('SUMMARY:1교시 과학\\, 실험\\;\\n준비', body.decode('utf-8').replace('\r\n ', ''))
            self.assertEqual(body.count(b'BEGIN:VEVENT'), 2)
            self.assertEqual(body.count(b'UID:'), 2)
            self.assertEqual(fetch.call_count, 2)
            self.assertEqual(fetch.call_args_list[0].args[1], start.isoformat())

            status, _, body2 = dispatch_request('GET', '/api/v1/timetable.ics', query, cache)
            self.assertEqual((status, body2), (200, body))
            status, _, body_json = dispatch_request('GET', '/api/v1/timetable',
                                                  f'school=2%3AExample&week={start.isoformat()}', cache)
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(body_json)['cacheStatus'], 'hit')
            self.assertEqual(fetch.call_count, 2)

    def test_ical_subscription_rejects_bad_parameters_before_fetching(self):
        with patch('backend.app.fetch_timetable') as fetch:
            for query in (
                'school=2%3AExample&grade=2',
                'school=2%3AExample&class=3',
                'school=2%3AExample&grade=0&class=3',
                'school=2%3AExample&grade=2&class=0',
                'school=2%3AExample&grade=2&class=3&weeks=3',
                'school=2%3AExample&grade=2&class=3&weeks=1&weeks=2',
                'school=2%3AExample&grade=2&class=3&mode=invalid',
                'school=2%3AExample&grade=2&class=3&mode=summary&mode=periods',
            ):
                with self.subTest(query=query):
                    status, _, body = dispatch_request('GET', '/api/v1/timetable.ics', query)
                    self.assertEqual((status, json.loads(body)['code']), (400, 'invalid_request'))
            fetch.assert_not_called()

    def test_calendar_summary_and_conditional_requests(self):
        def fake_fetch(school, week):
            return {'schoolId': school, 'weekStart': week, 'fetchedAt': '2026-11-14T00:00:00Z',
                    'records': [dict(grade=2, **{'class': 3}, date=week, period=period, subject=subject)
                                for period, subject in enumerate(subjects, 1)]}

        subjects = ['수학', '과학']
        path = '/api/v1/timetable.ics'
        query = 'school=2%3AExample&grade=2&class=3&weeks=2'
        summary = query + '&mode=summary'
        with patch('backend.app.fetch_timetable', side_effect=fake_fetch) as fetch, \
                patch.dict('os.environ', {'OPENCIGAN_HISTORY_DB': ''}):
            cache = Cache()
            self.assertEqual(dispatch_request('GET', path, query, cache)[2].count(b'BEGIN:VEVENT'), 4)
            status, headers, body = dispatch_request('GET', path, summary, cache)
            self.assertEqual((status, body.count(b'BEGIN:VEVENT')), (200, 2))
            self.assertIn('1교시 수학\\n2교시 과학', body.decode().replace('\r\n ', ''))
            for method, validator in [('GET', '"other", W/' + headers['ETag']), ('HEAD', '*')]:
                status, cached_headers, cached_body = dispatch_request(
                    method, path, summary, cache, request_headers={'If-None-Match': validator})
                self.assertEqual((status, cached_headers['ETag'], cached_body), (304, headers['ETag'], b''))
                self.assertNotIn('Content-Length', cached_headers)
            self.assertEqual(fetch.call_count, 2)
            subjects[1] = '영어'
            status, next_headers, next_body = dispatch_request(
                'GET', path, summary, Cache(), request_headers={'If-None-Match': headers['ETag']})
            self.assertEqual(status, 200)
            self.assertNotEqual(next_headers['ETag'], headers['ETag'])
            self.assertEqual([line for line in body.splitlines() if line.startswith(b'UID:')],
                             [line for line in next_body.splitlines() if line.startswith(b'UID:')])

    def test_history_records_only_successful_fresh_fetches(self):
        from unittest.mock import Mock
        response = {'schoolId': '1:Example', 'weekStart': '2026-11-09', 'records': [],
                    'fetchedAt': '2026-11-09T00:00:00+00:00', 'stale': False}
        store = Mock()
        with patch('backend.app.validate_timetable_week'), patch('backend.app._history_store', return_value=store), \
                patch('backend.app.fetch_timetable', side_effect=[response, RuntimeError('unavailable')]):
            cache = Cache(ttl=0, retry_delay=60)
            query = 'school=1%3AExample&week=2026-11-09'
            first = json.loads(dispatch_request('GET', '/api/v1/timetable', query, cache)[2])
            second = json.loads(dispatch_request('GET', '/api/v1/timetable', query, cache)[2])
            self.assertEqual((first['cacheStatus'], second['cacheStatus']), ('miss', 'stale'))
            store.observe.assert_called_once()

    def test_source_update_tracking_requires_explicit_stats_flag(self):
        from unittest.mock import Mock
        from backend.app import _cached_timetable
        response = {'schoolId': '1:Example', 'weekStart': '2026-11-09', 'records': [],
                    'fetchedAt': '2026-11-09T00:00:00+00:00', 'sourceUpdatedAt': '2026-11-08T12:00:00+00:00', 'stale': False}
        for enabled in ('', '1'):
            with self.subTest(enabled=enabled), patch.dict('os.environ', {'OPENCIGAN_HISTORY_STATS_ENABLED': enabled}), \
                    patch('backend.app._history_store', return_value=Mock()) as get_store, \
                    patch('backend.app.fetch_timetable', return_value=response):
                _cached_timetable('1:Example', '2026-11-09', Cache())
                kwargs = get_store.return_value.observe.call_args.kwargs
                self.assertEqual(kwargs['source_updated_at'], response['sourceUpdatedAt'])
                self.assertEqual(kwargs['track_source_updates'], enabled == '1')

    def test_history_endpoint_with_synthetic_data(self):
        import tempfile
        from pathlib import Path
        from backend.history import HistoryStore
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / 'history.sqlite')
            store = HistoryStore(path)
            record = {'grade': 1, 'class': 2, 'date': '2026-11-09', 'period': 1, 'subject': 'Math', 'teacher': 'A'}
            store.observe('1:Example', '2026-11-09', [record])
            store.observe('1:Example', '2026-11-09', [{**record, 'subject': 'Art'}])
            with patch.dict('os.environ', {'OPENCIGAN_HISTORY_DB': path}):
                status, _, body = dispatch_request('GET', '/api/v1/timetable/history', 'school=1%3AExample&week=2026-11-09')
                self.assertEqual(status, 200)
                change = json.loads(body)['changes'][0]
                self.assertEqual((change['before']['subject'], change['after']['subject']), ('Math', 'Art'))

    def test_shutter_bypass_boundaries_status_admin_options(self):
        from unittest.mock import Mock
        from backend.shutter import Shutter
        closed_shutter = Shutter(max_requests=1, window_seconds=60, cooldown_seconds=30)
        closed_shutter.check()
        closed_shutter.check()

        # 1. /api/v1/status bypasses shutter
        status, _, body = dispatch_request('GET', '/api/v1/status', '', shutter_instance=closed_shutter)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)['status'], 'ok')

        # 2. OPTIONS requests bypass shutter across endpoints
        for path in ('/api/v1/schools', '/api/v1/timetable', '/api/v1/timetable.ics', '/api/v1/meals', '/api/v1/unknown'):
            with self.subTest(path=path):
                status, headers, body = dispatch_request('OPTIONS', path, '', shutter_instance=closed_shutter)
                self.assertEqual(status, 204)
                self.assertEqual(body, b'')

        # 3. /api/v1/admin/analytics bypasses shutter (handles auth independently)
        status, headers, body = dispatch_request(
            'GET', '/api/v1/admin/analytics', '', shutter_instance=closed_shutter
        )
        self.assertEqual(status, 401)

        with patch.dict('os.environ', {'OPENCIGAN_ADMIN_TOKEN': 'secret-token-123'}):
            mock_store = Mock()
            mock_store.summary.return_value = {'totalViews': 10}
            with patch('backend.app._analytics_store', return_value=mock_store):
                status, _, body = dispatch_request(
                    'GET', '/api/v1/admin/analytics', 'days=7',
                    request_headers={'Authorization': 'Bearer secret-token-123'},
                    shutter_instance=closed_shutter
                )
                self.assertEqual(status, 200)
                self.assertEqual(json.loads(body)['totalViews'], 10)

    def test_shutter_sheds_public_endpoints_with_503(self):
        from backend.shutter import Shutter
        closed_shutter = Shutter(max_requests=1, window_seconds=60, cooldown_seconds=30)
        closed_shutter.check()
        closed_shutter.check()

        for method, path in (
            ('GET', '/api/v1/schools'),
            ('GET', '/api/v1/timetable'),
            ('GET', '/api/v1/meals'),
            ('POST', '/api/v1/analytics/pageview'),
            ('GET', '/api/v1/unknown'),
        ):
            with self.subTest(method=method, path=path):
                status, headers, body = dispatch_request(method, path, '', shutter_instance=closed_shutter)
                self.assertEqual(status, 503)
                self.assertEqual(headers.get('Retry-After'), '30')
                self.assertEqual(json.loads(body)['code'], 'service_overloaded')


if __name__ == '__main__':
    unittest.main()
