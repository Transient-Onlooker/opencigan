import unittest
from datetime import date, datetime, timedelta, timezone

from backend.scheduled_lessons import preparation_periods, scheduled_event_id, scheduled_time


class ScheduledLessonTests(unittest.TestCase):
    def test_kst_schedule_and_cross_midnight_quiet_hours(self):
        day = date(2026, 11, 23)
        self.assertEqual(scheduled_time(day, "08:30").isoformat(), "2026-11-23T08:30:00+09:00")
        self.assertEqual(scheduled_time(day, "23:30", {"start": "22:00", "end": "07:00"}).isoformat(), "2026-11-24T07:00:00+09:00")
        self.assertEqual(scheduled_time(day, "06:30", {"start": "22:00", "end": "07:00"}).isoformat(), "2026-11-23T07:00:00+09:00")
        with self.assertRaises(ValueError):
            scheduled_time(day, "25:00")

    def test_event_identity_is_stable_and_distinguishes_day_and_mode(self):
        day = date(2026, 11, 23)
        identifier = "a" * 24
        first = scheduled_event_id(identifier, "subject_prep", day)
        self.assertEqual(first, scheduled_event_id(identifier, "subject_prep", day))
        self.assertNotEqual(first, scheduled_event_id(identifier, "daily_summary", day))
        self.assertNotEqual(first, scheduled_event_id(identifier, "subject_prep", day + timedelta(days=1)))
        with self.assertRaises(ValueError):
            scheduled_event_id("bad", "subject_prep", day)

    def setUp(self):
        self.now = datetime.fromisoformat("2026-11-22T15:05:00+00:00")
        self.data = {"schoolId": "123:예시학교", "weekStart": "2026-11-23", "stale": False,
                     "fetchedAt": "2026-11-22T15:00:00Z", "records": [
                         {"date": "2026-11-23", "grade": 2, "class": 1, "period": 3, "subject": "체육"},
                         {"date": "2026-11-23", "grade": 2, "class": "1", "period": 1, "subject": "체육"},
                         {"date": "2026-11-23", "grade": 2, "class": 1, "period": 3, "subject": "체육"},
                         {"date": "2026-11-23", "grade": 2, "class": 2, "period": 2, "subject": "체육"},
                         {"date": "2026-11-23", "grade": 2, "class": 1, "period": 4, "subject": "체육이론"},
                     ]}

    def select(self):
        return preparation_periods(self.data, "123:예시학교", 2, 1, "체육", self.now, timedelta(minutes=30))

    def test_kst_day_class_exact_subject_and_multiple_periods(self):
        self.assertEqual(self.select(), [1, 3])
        self.assertEqual(preparation_periods(self.data, "123:예시학교", 2, 1, "수학", self.now, timedelta(minutes=30)), [])

    def test_unusable_data_never_becomes_a_no_lesson_result(self):
        for key, value in (("stale", True), ("schoolId", "456:다른학교"), ("weekStart", "2026-11-16"),
                           ("records", []), ("fetchedAt", "2026-11-22T14:00:00Z"),
                           ("fetchedAt", "2026-11-22T15:06:00Z"), ("fetchedAt", "2026-11-22T15:00:00")):
            original = self.data[key]
            self.data[key] = value
            with self.subTest(key=key, value=value):
                self.assertIsNone(self.select())
            self.data[key] = original

    def test_incomplete_records_are_not_used(self):
        self.data["records"].append({"grade": 2, "class": 1, "subject": "체육"})
        self.assertIsNone(self.select())

    def test_invalid_or_out_of_week_dates_are_not_used(self):
        for value in ("2026-11-35", "2026-11-16"):
            self.data["records"][0]["date"] = value
            with self.subTest(value=value):
                self.assertIsNone(self.select())


if __name__ == "__main__":
    unittest.main()
