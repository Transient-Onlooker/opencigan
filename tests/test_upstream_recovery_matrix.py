import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from backend.app import dispatch_request
from backend.cache import Cache


class UpstreamRecoveryTests(unittest.TestCase):
    def test_timetable_search_failure_does_not_block_neis_meals_or_other_searches(self):
        for error in (RuntimeError('HTTP 403'), RuntimeError('HTTP 429'), TimeoutError('delay')):
            with self.subTest(error=str(error)):
                cache = Cache(ttl=0, retry_delay=10)
                clock_value = [100]
                down = [True]
                def search(query):
                    if query == 'bad' and down[0]:
                        raise error
                    return [{'id': '1:Example', 'name': 'Example', 'region': 'region'}]
                meal = SimpleNamespace(date='2026-11-23', meal_type='중식', menu='밥', calories=None, nutrition=None, origin=None)
                with patch.dict('os.environ', {'NEIS_API_KEY': 'synthetic'}), \
                     patch('backend.cache.time.monotonic', side_effect=lambda: clock_value[0]), \
                     patch('backend.app.search_schools', side_effect=search), \
                     patch('backend.app.NEISClient.from_environment') as client:
                    client.return_value.get_meals.return_value = [meal]
                    status, headers, body = dispatch_request('GET', '/api/v1/schools', 'q=bad', cache)
                    self.assertEqual((status, json.loads(body)['code']), (503, 'upstream_unavailable'))
                    self.assertGreater(int(headers['Retry-After']), 0)
                    self.assertEqual(dispatch_request('GET', '/api/v1/schools', 'q=other', cache)[0], 200)
                    status, _, body = dispatch_request('GET', '/api/v1/meals', 'school=B10%3A1234567&from=2026-11-23&to=2026-11-23', cache)
                    self.assertEqual(status, 200)
                    self.assertEqual(json.loads(body)['meals'][0]['dishes'], ['밥'])
                    down[0], clock_value[0] = False, 111
                    self.assertEqual(dispatch_request('GET', '/api/v1/schools', 'q=bad', cache)[0], 200)

    def test_failed_school_week_does_not_poison_other_school_or_week_and_recovers(self):
        for failure in (RuntimeError('HTTP 403'), RuntimeError('HTTP 429'), TimeoutError('delayed')):
            with self.subTest(failure=type(failure).__name__, message=str(failure)):
                cache = Cache(ttl=0, retry_delay=10)
                failed = False

                def fetch(school, week):
                    if school == '1:A' and week == '2026-11-09' and not failed:
                        raise failure
                    return {'schoolId': school, 'weekStart': week, 'records': [], 'stale': False}

                def request(school, week):
                    return dispatch_request('GET', '/api/v1/timetable', f'school={school}&week={week}', cache)

                with patch('backend.cache.time.monotonic', return_value=100) as clock, \
                     patch('backend.app.validate_timetable_week'), patch('backend.app.fetch_timetable', side_effect=fetch), \
                     patch('backend.app._history_store', return_value=None):
                    status, headers, body = request('1%3AA', '2026-11-09')
                    self.assertEqual((status, json.loads(body)['code']), (503, 'upstream_unavailable'))
                    self.assertIn('Retry-After', headers)
                    for school, week in [('1%3AA', '2026-11-16'), ('2%3AB', '2026-11-09')]:
                        self.assertEqual(request(school, week)[0], 200)
                    status, _, body = dispatch_request('GET', '/api/v1/status', '', cache)
                    self.assertEqual((status, json.loads(body)['scope']), (200, 'process liveness'))
                    failed = True
                    clock.return_value = 111
                    status, _, body = request('1%3AA', '2026-11-09')
                    self.assertEqual((status, json.loads(body)['schoolId']), (200, '1:A'))

    def test_stale_timetable_is_preserved_on_upstream_failure_then_replaced(self):
        for failure in (RuntimeError('HTTP 403'), RuntimeError('HTTP 429'), TimeoutError('delayed')):
            with self.subTest(failure=str(failure)):
                cache = Cache(ttl=0, retry_delay=0)
                results = [
                    {'schoolId': '1:A', 'weekStart': '2026-11-09', 'records': [{'subject': 'old'}], 'stale': False},
                    failure,
                    {'schoolId': '1:A', 'weekStart': '2026-11-09', 'records': [{'subject': 'new'}], 'stale': False},
                ]
                with patch('backend.app.validate_timetable_week'), patch('backend.app.fetch_timetable', side_effect=results), \
                     patch('backend.app._history_store', return_value=None):
                    rows = []
                    for _ in range(3):
                        status, _, body = dispatch_request('GET', '/api/v1/timetable', 'school=1%3AA&week=2026-11-09', cache)
                        self.assertEqual(status, 200)
                        rows.append(json.loads(body))
                    self.assertEqual([row['records'][0]['subject'] for row in rows], ['old', 'old', 'new'])
                    self.assertEqual([row['stale'] for row in rows], [False, True, False])


if __name__ == '__main__':
    unittest.main()
