import unittest
from urllib.parse import urlencode
from unittest.mock import patch

from backend.app import dispatch_request


class IcalApiTimesTests(unittest.TestCase):
    def test_timed_feed_reuses_cache_and_revalidates_by_body(self):
        data = {'schoolId': '1:Example', 'records': [
            {'grade': 1, 'class': 2, 'date': '2026-11-09', 'period': 1, 'subject': 'Math', 'teacher': None},
            {'grade': 1, 'class': 2, 'date': '2026-11-09', 'period': 2, 'subject': 'Art', 'teacher': None},
        ], 'fetchedAt': '2026-11-09T00:00:00Z'}
        query = urlencode({'school': '1:Example', 'grade': 1, 'class': 2, 'mode': 'timed', 'times': '1:0900-0950'})
        with patch('backend.app._cached_timetable', return_value=(data, 'hit')) as cached:
            status, headers, body = dispatch_request('GET', '/api/v1/timetable.ics', query)
            self.assertEqual(status, 200)
            self.assertIn(b'DTSTART:20261109T000000Z', body)
            self.assertIn('교시 시각 미설정'.encode(), body)
            status, _, empty = dispatch_request('GET', '/api/v1/timetable.ics', query,
                                                request_headers={'If-None-Match': headers['ETag']})
            self.assertEqual((status, empty), (304, b''))
            changed = query.replace('0900-0950', '1000-1050')
            status, updated, _ = dispatch_request('GET', '/api/v1/timetable.ics', changed,
                                                  request_headers={'If-None-Match': headers['ETag']})
            self.assertEqual(status, 200)
            self.assertNotEqual(headers['ETag'], updated['ETag'])
            self.assertEqual(cached.call_count, 3)

    def test_invalid_times_rejected_before_upstream_access(self):
        for times in ['1:0900-0950,1:1000-1050', '1:0900-0950,2:0940-1000',
                      '1:2400-2500', '1:0900-0900', '21:0900-0950', '1:09:00-09:50',
                      '1:0900-0950\r\nBEGIN:VEVENT', 'x' * 401]:
            with self.subTest(times=times), patch('backend.app._cached_timetable') as cached:
                query = urlencode({'school': '1:Example', 'grade': 1, 'class': 2, 'mode': 'timed', 'times': times})
                status, _, _ = dispatch_request('GET', '/api/v1/timetable.ics', query)
                self.assertEqual(status, 400)
                cached.assert_not_called()
        with patch('backend.app._cached_timetable') as cached:
            status, _, _ = dispatch_request('GET', '/api/v1/timetable.ics',
                'school=1%3AExample&grade=1&class=2&mode=timed&times=1%3A0900-0950&times=2%3A1000-1050')
            self.assertEqual(status, 400)
            cached.assert_not_called()
