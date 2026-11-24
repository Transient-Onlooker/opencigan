import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

from backend.app import dispatch_request, make_app
from backend.history import HistoryStore


class HistoryStatsApiTests(unittest.TestCase):
    def setUp(self):
        self.path = '/api/v1/admin/history-stats'
        self.query = 'school=1%3AExample&week=2026-11-16'
        self.token = 'example-admin-token'
        self.store = Mock()
        self.store.change_stats.return_value = {'observed': False, 'totalChanges': None}

    def request(self, query=None, token=None):
        return dispatch_request('GET', self.path, self.query if query is None else query,
                                request_headers={'Authorization': 'Bearer ' + (token or '')})

    def test_default_off_and_authorization(self):
        with patch.dict('os.environ', {'OPENCIGAN_HISTORY_STATS_ENABLED': '', 'OPENCIGAN_ANALYTICS_ADMIN_TOKEN': self.token}), \
             patch('backend.app._history_store') as store:
            self.assertEqual(self.request(token=self.token)[0], 503)
            store.assert_not_called()
        with patch.dict('os.environ', {'OPENCIGAN_HISTORY_STATS_ENABLED': '1', 'OPENCIGAN_ANALYTICS_ADMIN_TOKEN': self.token}), \
             patch('backend.app._history_store') as store:
            self.assertEqual(self.request(token='wrong')[0], 401)
            store.assert_not_called()

    def test_validated_scope_and_unobserved_result(self):
        with patch.dict('os.environ', {'OPENCIGAN_HISTORY_STATS_ENABLED': '1', 'OPENCIGAN_ANALYTICS_ADMIN_TOKEN': self.token}), \
             patch('backend.app._history_store', return_value=self.store):
            status, _, body = self.request(token=self.token)
            self.assertEqual(status, 200)
            self.assertIsNone(json.loads(body)['totalChanges'])
            self.store.change_stats.assert_called_once_with('1:Example', '2026-11-16')
            for query in ('school=1%3AExample&week=2026-11-17', 'school=bad&week=2026-11-16',
                          'school=1%3AExample%0Ainvalid&week=2026-11-16',
                          self.query + '&week=2026-11-16', self.query + '&other=x'):
                self.assertEqual(self.request(query, self.token)[0], 400)

    def test_real_store_reports_only_observed_changes(self):
        temp_root = Path(os.environ['LOCALAPPDATA']) / 'Temp' if os.name == 'nt' else None
        with tempfile.TemporaryDirectory(dir=temp_root) as tmp:
            path = str(Path(tmp) / 'history.sqlite')
            store = HistoryStore(path)
            base = datetime.now(timezone.utc)
            lesson = {'grade': 1, 'class': 1, 'date': '2026-11-16', 'period': 1, 'subject': 'Math', 'teacher': 'A'}
            store.observe('1:Example', '2026-11-16', [lesson], base)
            store.observe('1:Example', '2026-11-16', [{**lesson, 'subject': 'Science'}], base + timedelta(seconds=1))
            with patch.dict('os.environ', {'OPENCIGAN_HISTORY_STATS_ENABLED': '1',
                                          'OPENCIGAN_HISTORY_DB': path,
                                          'OPENCIGAN_ANALYTICS_ADMIN_TOKEN': self.token}):
                status, _, body = self.request(token=self.token)
            result = json.loads(body)
            self.assertEqual(status, 200)
            self.assertTrue(result['observed'])
            self.assertEqual(result['totalChanges'], 1)
            self.assertEqual(result['byType']['changed'], 1)
            observed_day = (base + timedelta(seconds=1)).astimezone(timezone(timedelta(hours=9))).date().isoformat()
            self.assertEqual(result['changesByObservedDay'], [{'date': observed_day, 'count': 1}])
            self.assertEqual(result['subjectPeriods'], [{'subject': 'Science', 'classPeriods': 1}])
            self.assertEqual(result['teacherOverlaps'], [])

    def test_wsgi_forwards_admin_authentication(self):
        environ = {'REQUEST_METHOD': 'GET', 'PATH_INFO': self.path, 'QUERY_STRING': self.query,
                   'REMOTE_ADDR': '127.0.0.1', 'HTTP_AUTHORIZATION': 'Bearer ' + self.token}
        statuses = []
        with patch.dict('os.environ', {'OPENCIGAN_HISTORY_STATS_ENABLED': '1',
                                      'OPENCIGAN_ANALYTICS_ADMIN_TOKEN': self.token}), \
             patch('backend.app._history_store', return_value=self.store):
            body = b''.join(make_app()(environ, lambda status, headers: statuses.append(status)))
        self.assertEqual(statuses, ['200 OK'])
        self.assertFalse(json.loads(body)['observed'])


if __name__ == '__main__':
    unittest.main()
