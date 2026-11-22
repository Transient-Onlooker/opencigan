import unittest
from datetime import datetime, timedelta, timezone

from backend.scheduled_lessons import preparation_periods


class ScheduledLessonTests(unittest.TestCase):
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
