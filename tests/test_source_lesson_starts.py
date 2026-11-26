import unittest
from types import SimpleNamespace
from unittest.mock import patch

from backend import timetable


class SourceLessonStartsTests(unittest.TestCase):
    def test_labelled_periods_are_not_inferred_from_array_position(self):
        cases = (
            ([None, '3(11:05)', '', '1(09:10)'], {'1': '09:10', '3': '11:05'}),
            (['09:00', '10:00', '11:00'], {}),
            (['2(10:00)', '1(09:10)', '2(10:00)'], {'1': '09:10'}),
            (['1 (09:10)', '2(10:00) extra', '3(11:05)', '4(9:10)'], {'3': '11:05'}),
            ((None, ' 1(09:10) ', '30(23:59)'), {'1': '09:10', '30': '23:59'}),
        )
        for source, expected in cases:
            with self.subTest(source=source):
                self.assertEqual(timetable._source_lesson_starts(source), expected)

    def test_only_unambiguous_labelled_valid_times_are_used(self):
        source = ["1(09:10)", "3(11:05)", "2(24:00)", "4(10:60)", "09:00", "5(10:00)",
                  "5(10:05)", "0(08:00)", "31(12:00)", "6(8:00)", None]
        self.assertEqual(timetable._source_lesson_starts(source), {"1": "09:10", "3": "11:05"})
        for value in (None, "1(09:10)", {}, []):
            with self.subTest(value=value):
                self.assertEqual(timetable._source_lesson_starts(value), {})

    def test_optional_source_times_do_not_change_other_fields(self):
        table = SimpleNamespace(timetable=[], update_date=None, day_time=["1(09:10)"])
        with patch.object(timetable, "configure_comcigan_proxy"), \
             patch.object(timetable, "validate_timetable_week", return_value=0), \
             patch("pycomcigan.TimeTable", return_value=table), \
             self.assertLogs("opensigan.timetable", level="INFO") as logs:
            result = timetable.fetch_timetable("1:School", "2026-11-23", include_original=True)
        self.assertEqual(result["sourceLessonStarts"], {"1": "09:10"})
        self.assertEqual(result["records"], [])
        self.assertIsNone(result["sourceUpdatedAt"])
        self.assertIn("timetable normalization duration_ms=", logs.output[0])
        self.assertNotIn("School", logs.output[0])
        self.assertNotIn("2026-11-23", logs.output[0])


if __name__ == "__main__":
    unittest.main()
