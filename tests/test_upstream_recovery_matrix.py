import json
import time
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import patch

from backend.app import dispatch_request
from backend.cache import Cache
from backend.comcigan_proxy import _deadline, with_comcigan_budget


class UpstreamRecoveryTests(unittest.TestCase):
    def setUp(self):
        patcher = patch('backend.app.shutter.check', return_value=(True, 0))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_same_key_wait_is_bounded_for_timetable_and_search(self):
        for path, query, target in (
            ('/api/v1/schools', 'q=Example', 'backend.app.search_schools'),
            ('/api/v1/timetable', 'school=1%3AExample&week=2026-11-23', 'backend.app.fetch_timetable'),
        ):
            with self.subTest(path=path):
                cache = Cache()
                entered, release = threading.Event(), threading.Event()
                def slow(*args):
                    entered.set()
                    if not release.wait(2):
                        raise AssertionError('fixture was not released')
                    if path.endswith('schools'):
                        return []
                    return {'schoolId': '1:Example', 'weekStart': '2026-11-23', 'records': [], 'stale': False}
                def request():
                    return dispatch_request('GET', path, query, cache)
                with patch('backend.comcigan_proxy.UPSTREAM_BUDGET_SECONDS', 0.05), \
                     patch('backend.app.validate_timetable_week'), patch('backend.app._history_store', return_value=None), \
                     patch(target, side_effect=slow), ThreadPoolExecutor(max_workers=2) as pool:
                    first = pool.submit(request)
                    self.assertTrue(entered.wait(1))
                    try:
                        status, _, body = pool.submit(request).result(timeout=1)
                        self.assertEqual(status, 503)
                        self.assertEqual(json.loads(body)['code'], 'upstream_unavailable')
                    finally:
                        release.set()
                    self.assertEqual(first.result(timeout=1)[0], 200)

    def test_two_week_calendar_shares_budget_and_keeps_stale_weeks(self):
        cache = Cache(ttl=0, retry_delay=10)
        seen = []

        def cached_data(school, week):
            return {'schoolId': school, 'weekStart': week, 'records': [], 'stale': False}

        @with_comcigan_budget
        def delayed_failure(school, week):
            seen.append((_deadline.get(), time.monotonic()))
            if len(seen) == 1:
                time.sleep(0.03)
            raise TimeoutError('simulated upstream timeout')

        query = 'school=1%3AExample&grade=1&class=1&weeks=2'
        with patch('backend.app.fetch_timetable', side_effect=cached_data), \
             patch('backend.app._history_store', return_value=None):
            self.assertEqual(dispatch_request('GET', '/api/v1/timetable.ics', query, cache)[0], 200)
        with patch('backend.app.fetch_timetable', side_effect=delayed_failure), \
             patch('backend.app._history_store', return_value=None):
            status, _, body = dispatch_request('GET', '/api/v1/timetable.ics', query, cache)
        self.assertEqual(status, 200)
        self.assertIn(b'BEGIN:VCALENDAR', body)
        self.assertEqual(len(seen), 2)
        self.assertEqual(seen[0][0], seen[1][0])
        self.assertLess(seen[1][0] - seen[1][1], seen[0][0] - seen[0][1])
        self.assertIsNone(_deadline.get())

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

    def test_neis_meal_failure_does_not_block_timetable_or_other_meal_ranges_and_recovers(self):
        for error in (RuntimeError('HTTP 403'), RuntimeError('HTTP 429'), TimeoutError('delay')):
            with self.subTest(error=str(error)):
                cache = Cache(ttl=0, retry_delay=10)
                clock_value = [100]
                down = [True]

                def mock_get_meals(school, start, end):
                    if school.office_code == 'B10' and down[0]:
                        raise error
                    return [SimpleNamespace(date=start.isoformat(), meal_type='중식', menu='밥', calories=None, nutrition=None, origin=None)]

                timetable_data = {'schoolId': '1:Example', 'weekStart': '2026-11-23', 'records': [{'subject': '국어'}], 'stale': False}

                with (
                    patch.dict('os.environ', {'NEIS_API_KEY': 'synthetic'}),
                    patch('backend.cache.time.monotonic', side_effect=lambda: clock_value[0]),
                    patch('backend.app.validate_timetable_week'),
                    patch('backend.app.fetch_timetable', return_value=timetable_data),
                    patch('backend.app._history_store', return_value=None),
                    patch('backend.app.NEISClient.from_environment') as client,
                ):
                    client.return_value.get_meals.side_effect = mock_get_meals

                    status, headers, body = dispatch_request('GET', '/api/v1/meals', 'school=B10%3A1234567&from=2026-11-23&to=2026-11-23', cache)
                    self.assertEqual((status, json.loads(body)['code']), (503, 'upstream_unavailable'))
                    self.assertGreater(int(headers['Retry-After']), 0)

                    status, _, body = dispatch_request('GET', '/api/v1/meals', 'school=C10%3A7654321&from=2026-11-23&to=2026-11-23', cache)
                    self.assertEqual(status, 200)
                    self.assertEqual(json.loads(body)['meals'][0]['dishes'], ['밥'])

                    status, _, body = dispatch_request('GET', '/api/v1/timetable', 'school=1%3AExample&week=2026-11-23', cache)
                    self.assertEqual(status, 200)
                    self.assertEqual(json.loads(body)['records'][0]['subject'], '국어')

                    status, _, body = dispatch_request('GET', '/api/v1/status', '', cache)
                    self.assertEqual((status, json.loads(body)['scope']), (200, 'process liveness'))

                    down[0], clock_value[0] = False, 111
                    status, _, body = dispatch_request('GET', '/api/v1/meals', 'school=B10%3A1234567&from=2026-11-23&to=2026-11-23', cache)
                    self.assertEqual(status, 200)
                    self.assertEqual(json.loads(body)['meals'][0]['dishes'], ['밥'])

    def test_neis_school_search_failure_does_not_block_timetable_and_recovers(self):
        for error in (RuntimeError('HTTP 403'), RuntimeError('HTTP 429'), TimeoutError('delay')):
            with self.subTest(error=str(error)):
                cache = Cache(ttl=0, retry_delay=10)
                clock_value = [100]
                down = [True]

                def mock_search_schools(name):
                    if name == 'bad' and down[0]:
                        raise error
                    return [SimpleNamespace(office_code='B10', school_code='1234567', name='정상고', kind='고등학교', address='서울')]

                with (
                    patch.dict('os.environ', {'NEIS_API_KEY': 'synthetic'}),
                    patch('backend.cache.time.monotonic', side_effect=lambda: clock_value[0]),
                    patch('backend.app.search_schools', return_value=[
                        {'id': '1:Comcigan', 'name': '컴시간고', 'region': '서울'},
                    ]),
                    patch('backend.app.NEISClient.from_environment') as client,
                ):
                    client.return_value.search_schools.side_effect = mock_search_schools

                    status, headers, body = dispatch_request('GET', '/api/v1/neis/schools', 'q=bad', cache)
                    self.assertEqual((status, json.loads(body)['code']), (503, 'upstream_unavailable'))
                    self.assertGreater(int(headers['Retry-After']), 0)

                    self.assertEqual(dispatch_request('GET', '/api/v1/schools', 'q=bad', cache)[0], 200)
                    self.assertEqual(dispatch_request('GET', '/api/v1/neis/schools', 'q=good', cache)[0], 200)

                    down[0], clock_value[0] = False, 111
                    self.assertEqual(dispatch_request('GET', '/api/v1/neis/schools', 'q=bad', cache)[0], 200)

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


    def test_calendar_preserves_stale_on_upstream_failure_and_recovers(self):
        for error in (RuntimeError('HTTP 403'), RuntimeError('HTTP 429'), TimeoutError('delay')):
            with self.subTest(error=str(error)):
                cache = Cache(ttl=0, retry_delay=10)
                clock_value = [100]
                results = [
                    {'schoolId': '1:Example', 'weekStart': '2026-11-23', 'records': [{'grade': 1, 'class': 1, 'date': '2026-11-23', 'period': 1, 'subject': 'OldMath', 'teacher': 'Kim'}], 'stale': False},
                    error,
                    {'schoolId': '1:Example', 'weekStart': '2026-11-23', 'records': [{'grade': 1, 'class': 1, 'date': '2026-11-23', 'period': 1, 'subject': 'NewMath', 'teacher': 'Kim'}], 'stale': False},
                ]
                with (
                    patch('backend.cache.time.monotonic', side_effect=lambda: clock_value[0]),
                    patch('backend.app.validate_timetable_week'),
                    patch('backend.app.fetch_timetable', side_effect=results),
                    patch('backend.app._history_store', return_value=None),
                ):
                    status, headers, body = dispatch_request('GET', '/api/v1/timetable.ics', 'school=1%3AExample&grade=1&class=1&weeks=1', cache)
                    self.assertEqual(status, 200)
                    self.assertIn(b'OldMath', body)

                    status, headers, body = dispatch_request('GET', '/api/v1/timetable.ics', 'school=1%3AExample&grade=1&class=1&weeks=1', cache)
                    self.assertEqual(status, 200)
                    self.assertIn(b'OldMath', body)

                    clock_value[0] = 111
                    status, headers, body = dispatch_request('GET', '/api/v1/timetable.ics', 'school=1%3AExample&grade=1&class=1&weeks=1', cache)
                    self.assertEqual(status, 200)
                    self.assertIn(b'NewMath', body)


if __name__ == '__main__':
    unittest.main()
