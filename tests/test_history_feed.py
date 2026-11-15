import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlencode
from xml.etree import ElementTree

from backend.app import _rate_clients, dispatch_request
from backend.history import HistoryStore


class HistoryFeedTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = HistoryStore(Path(self.temp.name) / "history.sqlite")
        self.now = datetime.now(timezone.utc)
        today = (self.now + timedelta(hours=9)).date()
        self.week = (today - timedelta(days=today.weekday())).isoformat()
        self.school = "2:예시&학교"
        self.query = urlencode({"school": self.school, "grade": 1, "class": 1, "week": self.week})
        self.path = "/api/v1/timetable/history.rss"
        _rate_clients.clear()

    def test_class_filter_xml_escaping_and_conditional_request(self):
        records = [dict(grade=1, date=self.week, period=i, subject="원래", teacher="", **{"class": 2}) for i in range(1, 61)]
        records.append(dict(grade=1, date=self.week, period=1, subject="수학", teacher="", **{"class": 1}))
        self.store.observe(self.school, self.week, records, self.now)
        changed = [{**record, "subject": "새 & <과목>\x01"} for record in records]
        self.store.observe(self.school, self.week, changed, self.now + timedelta(seconds=1))
        with patch("backend.app._history_store", return_value=self.store):
            status, headers, body = dispatch_request("GET", self.path, self.query)
            self.assertEqual(status, 200)
            self.assertTrue(headers["Content-Type"].startswith("application/rss+xml"))
            root = ElementTree.fromstring(body)
            self.assertEqual(root.findtext("channel/title"), "예시&학교 1학년 1반 시간표 변경")
            items = root.findall("channel/item")
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0].findtext("description"), "수학 → 새 &amp; &lt;과목&gt;")
            self.assertEqual(items[0].find("guid").get("isPermaLink"), "false")
            status, _, unchanged = dispatch_request("GET", self.path, self.query,
                                                     request_headers={"If-None-Match": headers["ETag"]})
            self.assertEqual((status, unchanged), (304, b""))

    def test_requires_class_and_disabled_history_is_not_exposed(self):
        with patch("backend.app._history_store", return_value=self.store):
            self.assertEqual(dispatch_request("GET", self.path, urlencode({"school": self.school, "grade": 1}))[0], 400)
            self.assertEqual(dispatch_request("GET", self.path, self.query + "&weekday=0")[0], 400)
            status, _, body = dispatch_request("GET", self.path, urlencode({"school": self.school, "grade": 1, "class": 1}))
            self.assertEqual(status, 200)
            self.assertEqual(len(ElementTree.fromstring(body).findall("channel/item")), 0)
        with patch("backend.app._history_store", return_value=None):
            status, _, body = dispatch_request("GET", self.path, self.query)
            self.assertEqual(status, 503)
            self.assertIn(b"history_disabled", body)

    def test_combined_filters_run_before_limit_and_match_both_sides(self):
        records = [dict(grade=1, date=self.week, period=i, subject="공통", teacher="A", **{"class": 1}) for i in range(2, 62)]
        records.append(dict(grade=1, date=self.week, period=1, subject="수학", teacher="김교사", **{"class": 1}))
        self.store.observe(self.school, self.week, records, self.now)
        changed = [{**record, "subject": "과학", "teacher": "박교사"} for record in records]
        self.store.observe(self.school, self.week, changed, self.now + timedelta(seconds=1))
        filters = urlencode({"subject": "수학", "teacher": "박교사", "weekday": 1, "period": 1, "type": "changed"})
        with patch("backend.app._history_store", return_value=self.store):
            status, _, body = dispatch_request("GET", self.path, self.query + "&" + filters)
            self.assertEqual(status, 200)
            items = ElementTree.fromstring(body).findall("channel/item")
            self.assertEqual(len(items), 1)
            self.assertIn("수학", items[0].findtext("description"))
            for bad in ("weekday=6", "period=21", "type=other", "teacher=a&teacher=b", "period=01", "subject="):
                with self.subTest(bad=bad):
                    self.assertEqual(dispatch_request("GET", self.path, self.query + "&" + bad)[0], 400)
