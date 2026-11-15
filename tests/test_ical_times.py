import hashlib
import unittest
from datetime import date

from backend.ical import render_timetable_ics


def _parse_ics_events(raw_bytes):
    text = raw_bytes.decode("utf-8")
    lines = text.split("\r\n")
    unfolded_lines = []
    for line in lines:
        if line.startswith(" "):
            if unfolded_lines:
                unfolded_lines[-1] += line[1:]
        else:
            unfolded_lines.append(line)
    events = []
    current = None
    for line in unfolded_lines:
        if line == "BEGIN:VEVENT":
            current = {}
        elif line == "END:VEVENT":
            if current is not None:
                events.append(current)
                current = None
        elif current is not None and ":" in line:
            prop, val = line.split(":", 1)
            current[prop] = val
    return events


class IcalTimesTests(unittest.TestCase):
    def setUp(self):
        self.school = "12345:테스트고등학교"
        self.grade = 2
        self.classroom = 3
        self.base_lesson_times = {
            1: {"start": "09:00", "end": "09:50"},
            2: {"start": "10:00", "end": "10:50"},
            3: {"start": "11:00", "end": "11:50"},
            4: {"start": "12:00", "end": "12:50"},
            5: {"start": "13:40", "end": "14:30"},
            6: {"start": "14:40", "end": "15:30"},
            7: {"start": "15:40", "end": "16:30"},
        }

    def test_timed_mode_basic_utc_conversion(self):
        timetables = [{
            "records": [
                {
                    "grade": 2, "class": 3, "date": "2026-03-23",
                    "period": 1, "subject": "국어", "teacher": "김선생", "isChanged": False,
                },
                {
                    "grade": 2, "class": 3, "date": "2026-03-23",
                    "period": 5, "subject": "수학", "teacher": "이선생", "isChanged": True,
                },
            ],
            "fetchedAt": "2026-03-22T00:00:00Z",
        }]
        ics = render_timetable_ics(self.school, self.grade, self.classroom, timetables,
                                   mode="timed", lesson_times=self.base_lesson_times)
        events = _parse_ics_events(ics)
        self.assertEqual(len(events), 2)

        # 1교시 09:00~09:50 KST -> 00:00~00:50 UTC
        self.assertEqual(events[0]["DTSTART"], "20260323T000000Z")
        self.assertEqual(events[0]["DTEND"], "20260323T005000Z")
        self.assertEqual(events[0]["SUMMARY"], "1교시 국어")
        self.assertIn("1교시", events[0]["DESCRIPTION"])
        self.assertIn("교사: 김선생", events[0]["DESCRIPTION"])
        self.assertNotIn("교시 시각 미설정", events[0]["DESCRIPTION"])

        # 5교시 13:40~14:30 KST -> 04:40~05:30 UTC
        self.assertEqual(events[1]["DTSTART"], "20260323T044000Z")
        self.assertEqual(events[1]["DTEND"], "20260323T053000Z")
        self.assertEqual(events[1]["SUMMARY"], "5교시 수학")
        self.assertIn("변경된 수업", events[1]["DESCRIPTION"])

    def test_timed_mode_utc_rollover_previous_day(self):
        early_times = {
            1: {"start": "08:30", "end": "09:20"},
            2: {"start": "07:00", "end": "07:50"},
            3: {"start": "08:00", "end": "08:50"},
        }
        timetables = [{
            "records": [
                {
                    "grade": 2, "class": 3, "date": "2026-03-23",
                    "period": 1, "subject": "아침자율", "isChanged": False,
                },
                {
                    "grade": 2, "class": 3, "date": "2026-05-01",
                    "period": 2, "subject": "새벽동아리", "isChanged": False,
                },
                {
                    "grade": 2, "class": 3, "date": "2026-01-01",
                    "period": 3, "subject": "신년특강", "isChanged": False,
                },
            ],
            "fetchedAt": "2026-03-22T00:00:00Z",
        }]
        ics = render_timetable_ics(self.school, self.grade, self.classroom, timetables,
                                   mode="timed", lesson_times=early_times)
        events = _parse_ics_events(ics)

        # 2026-01-01 08:00 KST -> 2025-12-31 23:00 UTC, ends 2025-12-31 23:50 UTC
        new_year_event = [e for e in events if "신년특강" in e["SUMMARY"]][0]
        self.assertEqual(new_year_event["DTSTART"], "20251231T230000Z")
        self.assertEqual(new_year_event["DTEND"], "20251231T235000Z")

        # 2026-03-23 08:30 KST -> 2026-03-22 23:30 UTC, ends 09:20 KST -> 2026-03-23 00:20 UTC
        march_event = [e for e in events if "아침자율" in e["SUMMARY"]][0]
        self.assertEqual(march_event["DTSTART"], "20260322T233000Z")
        self.assertEqual(march_event["DTEND"], "20260323T002000Z")

        # 2026-05-01 07:00 KST -> 2026-04-30 22:00 UTC (month rollover)
        may_event = [e for e in events if "새벽동아리" in e["SUMMARY"]][0]
        self.assertEqual(may_event["DTSTART"], "20260430T220000Z")
        self.assertEqual(may_event["DTEND"], "20260430T225000Z")

    def test_missing_period_times_fallback_to_allday(self):
        partial_times = {
            1: {"start": "09:00", "end": "09:50"},
        }
        timetables = [{
            "records": [
                {
                    "grade": 2, "class": 3, "date": "2026-03-23",
                    "period": 1, "subject": "국어", "teacher": "김선생",
                },
                {
                    "grade": 2, "class": 3, "date": "2026-03-23",
                    "period": 2, "subject": "영어", "teacher": "박선생",
                },
                {
                    "grade": 2, "class": 3, "date": "2026-03-23",
                    "period": 8, "subject": "방과후",
                },
            ],
            "fetchedAt": "2026-03-22T00:00:00Z",
        }]
        ics = render_timetable_ics(self.school, self.grade, self.classroom, timetables,
                                   mode="timed", lesson_times=partial_times)
        events = _parse_ics_events(ics)
        self.assertEqual(len(events), 3)

        # Period 1: timed
        self.assertEqual(events[0]["DTSTART"], "20260323T000000Z")
        self.assertEqual(events[0]["DTEND"], "20260323T005000Z")
        self.assertNotIn("교시 시각 미설정", events[0]["DESCRIPTION"])

        # Period 2: missing time -> all-day
        self.assertEqual(events[1]["DTSTART;VALUE=DATE"], "20260323")
        self.assertEqual(events[1]["DTEND;VALUE=DATE"], "20260324")
        self.assertIn("교시 시각 미설정", events[1]["DESCRIPTION"])
        self.assertIn("교사: 박선생", events[1]["DESCRIPTION"])

        # Period 8: missing time -> all-day
        self.assertEqual(events[2]["DTSTART;VALUE=DATE"], "20260323")
        self.assertEqual(events[2]["DTEND;VALUE=DATE"], "20260324")
        self.assertIn("교시 시각 미설정", events[2]["DESCRIPTION"])

    def test_missing_all_times_when_lesson_times_is_none(self):
        timetables = [{
            "records": [
                {"grade": 2, "class": 3, "date": "2026-03-23", "period": 1, "subject": "수학"},
            ],
            "fetchedAt": "2026-03-22T00:00:00Z",
        }]
        ics = render_timetable_ics(self.school, self.grade, self.classroom, timetables,
                                   mode="timed", lesson_times=None)
        events = _parse_ics_events(ics)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["DTSTART;VALUE=DATE"], "20260323")
        self.assertEqual(events[0]["DTEND;VALUE=DATE"], "20260324")
        self.assertIn("교시 시각 미설정", events[0]["DESCRIPTION"])

    def test_invalid_lesson_times_raises_value_error(self):
        timetables = [{"records": [], "fetchedAt": "2026-03-22T00:00:00Z"}]

        # Not a dict
        with self.assertRaises(ValueError):
            render_timetable_ics(self.school, self.grade, self.classroom, timetables,
                                 mode="timed", lesson_times=["not a dict"])

        # Invalid period key (< 1 or > 20 or not int)
        with self.assertRaises(ValueError):
            render_timetable_ics(self.school, self.grade, self.classroom, timetables,
                                 mode="timed", lesson_times={0: {"start": "09:00", "end": "09:50"}})
        with self.assertRaises(ValueError):
            render_timetable_ics(self.school, self.grade, self.classroom, timetables,
                                 mode="timed", lesson_times={21: {"start": "09:00", "end": "09:50"}})
        with self.assertRaises(ValueError):
            render_timetable_ics(self.school, self.grade, self.classroom, timetables,
                                 mode="timed", lesson_times={"1": {"start": "09:00", "end": "09:50"}})

        # Invalid entry structure or types
        with self.assertRaises(ValueError):
            render_timetable_ics(self.school, self.grade, self.classroom, timetables,
                                 mode="timed", lesson_times={1: "not a dict"})
        with self.assertRaises(ValueError):
            render_timetable_ics(self.school, self.grade, self.classroom, timetables,
                                 mode="timed", lesson_times={1: {"start": 900, "end": 950}})

        # Invalid HH:MM format
        with self.assertRaises(ValueError):
            render_timetable_ics(self.school, self.grade, self.classroom, timetables,
                                 mode="timed", lesson_times={1: {"start": "9:00", "end": "09:50"}})
        with self.assertRaises(ValueError):
            render_timetable_ics(self.school, self.grade, self.classroom, timetables,
                                 mode="timed", lesson_times={1: {"start": "25:00", "end": "25:50"}})

        # Start >= End
        with self.assertRaises(ValueError):
            render_timetable_ics(self.school, self.grade, self.classroom, timetables,
                                 mode="timed", lesson_times={1: {"start": "09:50", "end": "09:00"}})
        with self.assertRaises(ValueError):
            render_timetable_ics(self.school, self.grade, self.classroom, timetables,
                                 mode="timed", lesson_times={1: {"start": "09:00", "end": "09:00"}})

    def test_single_lesson_uid_stable_across_subject_and_teacher_changes(self):
        r_orig = {"grade": 2, "class": 3, "date": "2026-03-23", "period": 1, "subject": "국어", "teacher": "김선생"}
        r_subj_change = {"grade": 2, "class": 3, "date": "2026-03-23", "period": 1, "subject": "수학", "teacher": "이선생", "isChanged": True}

        ics_orig = render_timetable_ics(self.school, self.grade, self.classroom,
                                        [{"records": [r_orig], "fetchedAt": "2026-03-22T00:00:00Z"}],
                                        mode="timed", lesson_times=self.base_lesson_times)
        ics_changed = render_timetable_ics(self.school, self.grade, self.classroom,
                                           [{"records": [r_subj_change], "fetchedAt": "2026-03-22T00:00:00Z"}],
                                           mode="timed", lesson_times=self.base_lesson_times)

        ev_orig = _parse_ics_events(ics_orig)[0]
        ev_changed = _parse_ics_events(ics_changed)[0]

        # UID must be identical regardless of subject/teacher/isChanged changes
        self.assertEqual(ev_orig["UID"], ev_changed["UID"])
        expected_id = f"{self.school}|{self.grade}|{self.classroom}|2026-03-23|1"
        expected_uid = hashlib.sha256(expected_id.encode("utf-8")).hexdigest()[:32] + "@opencigan"
        self.assertEqual(ev_orig["UID"], expected_uid)

    def test_backward_compatibility_periods_mode(self):
        timetables = [{
            "records": [
                {"grade": 2, "class": 3, "date": "2026-03-23", "period": 1, "subject": "국어", "teacher": "김선생"},
            ],
            "fetchedAt": "2026-03-22T00:00:00Z",
        }]
        ics = render_timetable_ics(self.school, self.grade, self.classroom, timetables,
                                   mode="periods", lesson_times=self.base_lesson_times)
        events = _parse_ics_events(ics)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["DTSTART;VALUE=DATE"], "20260323")
        self.assertEqual(events[0]["DTEND;VALUE=DATE"], "20260324")
        self.assertNotIn("교시 시각 미설정", events[0]["DESCRIPTION"])

        expected_id = f"{self.school}|{self.grade}|{self.classroom}|2026-03-23|1"
        expected_uid = hashlib.sha256(expected_id.encode("utf-8")).hexdigest()[:32] + "@opencigan"
        self.assertEqual(events[0]["UID"], expected_uid)

    def test_backward_compatibility_summary_mode(self):
        r1 = {"grade": 2, "class": 3, "date": "2026-03-23", "period": 2, "subject": "수학", "teacher": "이선생", "isChanged": True}
        r2 = {"grade": 2, "class": 3, "date": "2026-03-23", "period": 1, "subject": "국어", "teacher": "김선생", "isChanged": False}
        records = [r1, r2]
        records_copy = [dict(x) for x in records]
        timetables = [{"records": records, "fetchedAt": "2026-03-22T00:00:00Z"}]
        ics = render_timetable_ics(self.school, self.grade, self.classroom, timetables,
                                   mode="summary", lesson_times=self.base_lesson_times)
        self.assertEqual(records, records_copy)
        events = _parse_ics_events(ics)
        self.assertEqual(len(events), 1)
        expected_id = f"{self.school}|{self.grade}|{self.classroom}|2026-03-23|summary"
        expected_uid = hashlib.sha256(expected_id.encode("utf-8")).hexdigest()[:32] + "@opencigan"
        self.assertEqual(events[0]["UID"], expected_uid)
        self.assertEqual(events[0]["SUMMARY"], "테스트고등학교 2학년 3반 · 2개 수업")
        self.assertEqual(events[0]["DTSTART;VALUE=DATE"], "20260323")
        self.assertEqual(events[0]["DTEND;VALUE=DATE"], "20260324")
        self.assertIn("1교시 국어 · 김선생", events[0]["DESCRIPTION"])
        self.assertIn("2교시 수학 · 이선생 (변경)", events[0]["DESCRIPTION"])

    def test_timed_mode_multiple_records_and_missing_times(self):
        r1 = {"grade": 2, "class": 3, "date": "2026-03-23", "period": 1, "subject": "화학", "teacher": "김선생"}
        r2 = {"grade": 2, "class": 3, "date": "2026-03-23", "period": 1, "subject": "생명", "teacher": "이선생"}
        r3 = {"grade": 2, "class": 3, "date": "2026-03-23", "period": 9, "subject": "야간A"}
        r4 = {"grade": 2, "class": 3, "date": "2026-03-23", "period": 9, "subject": "야간B"}
        timetables = [{"records": [r2, r1, r4, r3], "fetchedAt": "2026-03-22T00:00:00Z"}]
        ics = render_timetable_ics(self.school, self.grade, self.classroom, timetables,
                                   mode="timed", lesson_times={1: {"start": "09:00", "end": "09:50"}})
        events = _parse_ics_events(ics)
        self.assertEqual(len(events), 4)

        p1_events = [e for e in events if "1교시" in e["SUMMARY"]]
        self.assertEqual(len(p1_events), 2)
        for e in p1_events:
            self.assertEqual(e["DTSTART"], "20260323T000000Z")
            self.assertEqual(e["DTEND"], "20260323T005000Z")
            self.assertNotIn("교시 시각 미설정", e["DESCRIPTION"])
        self.assertNotEqual(p1_events[0]["UID"], p1_events[1]["UID"])

        p9_events = [e for e in events if "9교시" in e["SUMMARY"]]
        self.assertEqual(len(p9_events), 2)
        for e in p9_events:
            self.assertEqual(e["DTSTART;VALUE=DATE"], "20260323")
            self.assertEqual(e["DTEND;VALUE=DATE"], "20260324")
            self.assertIn("교시 시각 미설정", e["DESCRIPTION"])
        self.assertNotEqual(p9_events[0]["UID"], p9_events[1]["UID"])

    def test_same_period_multiple_records_uid_stability_and_no_collision(self):
        r1 = {"grade": 2, "class": 3, "date": "2026-03-23", "period": 1, "subject": "선택A", "teacher": "김선생"}
        r2 = {"grade": 2, "class": 3, "date": "2026-03-23", "period": 1, "subject": "선택B", "teacher": "이선생"}
        r3 = {"grade": 2, "class": 3, "date": "2026-03-23", "period": 2, "subject": "단일수업", "teacher": "박선생"}

        list1 = [r1, r2, r3]
        list1_copy = [dict(x) for x in list1]
        ics1 = render_timetable_ics(self.school, self.grade, self.classroom,
                                    [{"records": list1, "fetchedAt": "2026-03-22T00:00:00Z"}],
                                    mode="periods")
        self.assertEqual(list1, list1_copy)

        list2 = [r2, r1, r3]
        ics2 = render_timetable_ics(self.school, self.grade, self.classroom,
                                    [{"records": list2, "fetchedAt": "2026-03-22T00:00:00Z"}],
                                    mode="periods")

        events1 = _parse_ics_events(ics1)
        events2 = _parse_ics_events(ics2)
        self.assertEqual(len(events1), 3)
        self.assertEqual(len(events2), 3)

        uids1 = [e["UID"] for e in events1]
        self.assertEqual(len(uids1), len(set(uids1)))

        summary_to_uid1 = {e["SUMMARY"]: e["UID"] for e in events1}
        summary_to_uid2 = {e["SUMMARY"]: e["UID"] for e in events2}
        self.assertEqual(summary_to_uid1, summary_to_uid2)

        expected_single_id = f"{self.school}|{self.grade}|{self.classroom}|2026-03-23|2"
        expected_single_uid = hashlib.sha256(expected_single_id.encode("utf-8")).hexdigest()[:32] + "@opencigan"
        self.assertEqual(summary_to_uid1["2교시 단일수업"], expected_single_uid)

    def test_escaping_and_folding(self):
        special_subject = "특별활동, 심화; 실험\\실습\n프로젝트 " + ("매우긴과목명" * 15)
        timetables = [{
            "records": [
                {"grade": 2, "class": 3, "date": "2026-03-23", "period": 1,
                 "subject": special_subject, "teacher": "홍,길;동\\선생\n담당"},
            ],
            "fetchedAt": "2026-03-22T00:00:00Z",
        }]
        raw_ics = render_timetable_ics(self.school, self.grade, self.classroom, timetables)
        text = raw_ics.decode("utf-8")

        for line in text.split("\r\n"):
            self.assertLessEqual(len(line.encode("utf-8")), 75)

        self.assertIn("\\,", text)
        self.assertIn("\\;", text)
        self.assertIn("\\\\", text)
        self.assertIn("\\n", text)


if __name__ == "__main__":
    unittest.main()
