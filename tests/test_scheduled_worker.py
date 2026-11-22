import json
import os
import tempfile
import unittest
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from backend.cache import Cache
from backend.history import HistoryStore
from backend.scheduled_lessons import KST
from backend.scheduled_store import ScheduledStore
from backend.scheduled_worker import main, run_once
from backend.webhook_store import WebhookStore


class ScheduledWorkerTests(unittest.TestCase):
    def setUp(self):
        root = Path.home() / "AppData" / "Local" / "Temp" if os.name == "nt" else None
        self.directory = tempfile.TemporaryDirectory(dir=root)
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "history.sqlite"
        self.history = HistoryStore(self.path)
        self.webhooks = WebhookStore(self.path)
        self.schedules = ScheduledStore(self.path)
        self.now = datetime.now(KST).replace(hour=8, minute=0, second=0, microsecond=0)
        self.day = self.now.date()
        self.week = (self.day - timedelta(days=self.day.weekday())).isoformat()

    def subscribe(self, mode, clock="07:30", subject=None):
        subscription = self.webhooks.create("2:Example School", 2, 3, "https://discord.com/api/webhooks/123/secret")
        self.schedules.set_schedule(subscription["id"], subscription["token"], mode, clock, subject)
        return subscription

    def timetable(self):
        return {"schoolId": "2:Example School", "weekStart": self.week, "stale": False,
                "fetchedAt": (self.now - timedelta(minutes=5)).isoformat(), "records": [
                    {"date": self.day.isoformat(), "grade": 2, "class": 3, "period": 1, "subject": "체육", "teacher": "Kim"},
                    {"date": self.day.isoformat(), "grade": 2, "class": 3, "period": 3, "subject": "체육", "teacher": "Kim"},
                ]}

    def test_default_is_inert(self):
        self.assertEqual(run_once(None, None, None, self.now), 0)
        with patch.dict("os.environ", {}, clear=True), self.assertRaises(SystemExit):
            main()

    def test_morning_is_deduplicated_and_same_school_fetch_is_shared(self):
        first = self.subscribe("subject_prep", subject="체육")
        second = self.subscribe("subject_prep", subject="체육")
        calls = []
        def fetch(school, week):
            calls.append((school, week))
            return self.timetable()
        cache = Cache()
        self.assertEqual(run_once(self.schedules, cache, fetch, self.now, enabled=True), 2)
        self.assertEqual(run_once(self.schedules, cache, fetch, self.now + timedelta(minutes=1), enabled=True), 0)
        self.assertEqual(calls, [("2:Example School", self.week)])
        self.assertEqual(len(self.webhooks.deliveries(first["id"], first["token"])), 1)
        self.assertEqual(len(self.webhooks.deliveries(second["id"], second["token"])), 1)
        delivery = self.webhooks.claim(now=self.now.timestamp())
        self.assertIn("1교시, 3교시", json.loads(delivery["body"])["content"])

    def test_stale_or_failed_data_never_queues_and_can_recover(self):
        sub = self.subscribe("subject_prep", subject="체육")
        stale = {**self.timetable(), "stale": True}
        self.assertEqual(run_once(self.schedules, Cache(), lambda *_: stale, self.now, enabled=True), 0)
        self.assertEqual(run_once(self.schedules, Cache(), lambda *_: (_ for _ in ()).throw(TimeoutError()), self.now, enabled=True), 0)
        self.assertEqual(self.webhooks.deliveries(sub["id"], sub["token"]), [])
        self.assertEqual(run_once(self.schedules, Cache(), lambda *_: self.timetable(), self.now, enabled=True), 1)

    def test_failed_fetch_respects_backoff_before_recovery(self):
        sub = self.subscribe("subject_prep", subject="Math")
        timetable = self.timetable()
        for record in timetable["records"]:
            record["subject"] = "Math"
        calls = []

        def fetch(*_):
            calls.append(1)
            if len(calls) == 1:
                raise TimeoutError()
            return timetable

        cache = Cache(retry_delay=60)
        with patch("backend.cache.time.monotonic", return_value=100):
            self.assertEqual(run_once(self.schedules, cache, fetch, self.now, enabled=True), 0)
            self.assertEqual(run_once(self.schedules, cache, fetch, self.now, enabled=True), 0)
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.webhooks.deliveries(sub["id"], sub["token"]), [])
        with patch("backend.cache.time.monotonic", return_value=161):
            self.assertEqual(run_once(self.schedules, cache, fetch, self.now, enabled=True), 1)
        self.assertEqual(len(calls), 2)

    def test_reconfiguration_during_fetch_does_not_queue_old_revision(self):
        sub = self.subscribe("subject_prep", subject="체육")
        def fetch(*_):
            self.schedules.set_schedule(sub["id"], sub["token"], "immediate", "07:30")
            return self.timetable()
        self.assertEqual(run_once(self.schedules, Cache(), fetch, self.now, enabled=True), 0)
        self.assertEqual(self.webhooks.deliveries(sub["id"], sub["token"]), [])

    def test_filter_change_during_fetch_does_not_queue_old_selection(self):
        sub = self.subscribe("subject_prep", subject="체육")
        def fetch(*_):
            self.webhooks.update_filters(sub["id"], sub["token"], {"teacher": "Other"})
            return self.timetable()
        cache = Cache()
        self.assertEqual(run_once(self.schedules, cache, fetch, self.now, enabled=True), 0)
        self.assertEqual(self.webhooks.deliveries(sub["id"], sub["token"]), [])
        self.assertEqual(run_once(self.schedules, cache, fetch, self.now, enabled=True), 0)
        self.assertTrue(self.schedules.already_handled(sub["id"], "subject_prep", self.day.isoformat()))

    def test_no_matching_lesson_is_recorded_without_queueing(self):
        sub = self.subscribe("subject_prep", subject="Music")
        cache = Cache()
        self.assertEqual(run_once(self.schedules, cache, lambda *_: self.timetable(), self.now, enabled=True), 0)
        self.assertTrue(self.schedules.already_handled(sub["id"], "subject_prep", self.day.isoformat()))
        self.assertEqual(self.webhooks.deliveries(sub["id"], sub["token"]), [])

    def test_summary_applies_change_filters_and_queues_once(self):
        sub = self.subscribe("daily_summary")
        self.webhooks.update_filters(sub["id"], sub["token"], {"subject": "Science", "type": "changed"})
        lesson = {"date": self.day.isoformat(), "grade": 2, "class": 3, "period": 1, "subject": "Math", "teacher": "Kim"}
        with patch.dict("os.environ", {"OPENCIGAN_SCHEDULER_ENABLED": "1"}):
            self.history.observe("2:Example School", self.week, [lesson], self.now - timedelta(minutes=40))
            self.history.observe("2:Example School", self.week, [{**lesson, "subject": "Science"}], self.now - timedelta(minutes=35))
        self.assertEqual(run_once(self.schedules, Cache(), lambda *_: self.fail("summary must not fetch"), self.now, enabled=True), 1)
        self.assertEqual(run_once(self.schedules, Cache(), lambda *_: self.fail("summary must not fetch"), self.now, enabled=True), 0)
        delivery = self.webhooks.claim(now=self.now.timestamp())
        self.assertIn("Math", json.loads(delivery["body"])["content"])
        self.assertIn("Science", json.loads(delivery["body"])["content"])
        self.assertEqual(len(self.webhooks.deliveries(sub["id"], sub["token"])), 1)

    def test_summary_does_not_include_changes_observed_after_due_time(self):
        sub = self.subscribe("daily_summary")
        lesson = {"date": self.day.isoformat(), "grade": 2, "class": 3, "period": 1, "subject": "Math", "teacher": "Kim"}
        with patch.dict("os.environ", {"OPENCIGAN_SCHEDULER_ENABLED": "1"}):
            self.history.observe("2:Example School", self.week, [lesson], self.now - timedelta(minutes=40))
            self.history.observe("2:Example School", self.week, [{**lesson, "subject": "Science"}], self.now - timedelta(minutes=20))
        self.assertEqual(run_once(self.schedules, Cache(), lambda *_: self.fail("summary must not fetch"), self.now, enabled=True), 0)
        self.assertEqual(self.webhooks.deliveries(sub["id"], sub["token"]), [])

    def test_summary_deferred_across_midnight_uses_original_day(self):
        sub = self.subscribe("daily_summary", clock="23:00")
        self.webhooks.update_filters(sub["id"], sub["token"], {"quietHours": {"start": "22:00", "end": "07:00"}})
        yesterday = self.day - timedelta(days=1)
        week = (yesterday - timedelta(days=yesterday.weekday())).isoformat()
        observed = datetime.combine(yesterday, time(21, 0), KST)
        lesson = {"date": yesterday.isoformat(), "grade": 2, "class": 3, "period": 1, "subject": "Math", "teacher": "Kim"}
        with patch.dict("os.environ", {"OPENCIGAN_SCHEDULER_ENABLED": "1"}):
            self.history.observe("2:Example School", week, [lesson], observed)
            self.history.observe("2:Example School", week, [{**lesson, "subject": "Science"}], observed + timedelta(minutes=10))
        self.assertEqual(run_once(self.schedules, Cache(), lambda *_: self.fail("summary must not fetch"), self.now, enabled=True), 1)
        delivery = self.webhooks.claim(now=self.now.timestamp())
        self.assertIn(yesterday.isoformat(), json.loads(delivery["body"])["content"])
        self.assertEqual(len(self.webhooks.deliveries(sub["id"], sub["token"])), 1)


if __name__ == "__main__":
    unittest.main()
