import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlencode, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.app import dispatch_request
from opensigan.client import OpensiganClient


class BackendFilterContractTests(unittest.TestCase):
    def test_sdk_weekday_override_reaches_calendar_renderer(self):
        timetable = {
            "schoolId": "2:Example", "weekStart": "2026-11-09",
            "fetchedAt": "2026-11-09T00:00:00Z", "stale": False,
            "records": [
                {"grade": 1, "class": 1, "date": "2026-11-09", "period": 1, "subject": "Math", "teacher": None},
                {"grade": 1, "class": 1, "date": "2026-11-10", "period": 1, "subject": "Art", "teacher": None},
            ],
        }
        url = OpensiganClient().get_timetable_ics_url(
            "2:Example", 1, 1, mode="timed", times="1:0900-0950", weekday_times="2.1:1000-1050"
        )
        with patch("backend.app._cached_timetable", return_value=(timetable, "hit")):
            status, _, body = dispatch_request("GET", "/api/v1/timetable.ics", urlsplit(url).query)
        self.assertEqual(status, 200)
        self.assertIn(b"DTSTART:20261109T000000Z", body)
        self.assertIn(b"DTSTART:20261110T010000Z", body)
        self.assertIn(b"DTEND:20261110T015000Z", body)

    def test_teacher_substring_applies_to_json_and_all_ics_modes(self):
        timetable = {
            "schoolId": "2:Example", "weekStart": "2026-11-09",
            "fetchedAt": "2026-11-09T00:00:00Z", "stale": False,
            "records": [
                {"grade": 1, "class": 1, "date": "2026-11-09", "period": 1,
                 "subject": "Math", "teacher": "Kim Min"},
                {"grade": 1, "class": 1, "date": "2026-11-09", "period": 2,
                 "subject": "Science", "teacher": "Park"},
            ],
        }
        params = {"school": "2:Example", "week": "2026-11-09",
                  "grade": 1, "class": 1, "teacher": "kIM"}
        with patch("backend.app._cached_timetable", return_value=(timetable, "hit")), \
                patch("backend.app.validate_timetable_week"):
            status, _, body = dispatch_request("GET", "/api/v1/timetable", urlencode(params))
            self.assertEqual(status, 200)
            self.assertEqual([record["teacher"] for record in json.loads(body)["records"]], ["Kim Min"])
            for mode in ("periods", "summary", "timed"):
                with self.subTest(mode=mode):
                    status, _, body = dispatch_request(
                        "GET", "/api/v1/timetable.ics", urlencode({**params, "mode": mode}),
                    )
                    self.assertEqual(status, 200)
                    self.assertEqual(body.count(b"BEGIN:VEVENT"), 1)
                    self.assertIn(b"Math", body)
                    self.assertNotIn(b"Science", body)

    def test_timed_mode_times_parsing_contract(self):
        timetable = {
            "schoolId": "2:Example", "weekStart": "2026-11-09",
            "fetchedAt": "2026-11-09T00:00:00Z", "stale": False,
            "records": [
                {"grade": 1, "class": 1, "date": "2026-11-09", "period": 1, "subject": "Math", "teacher": None},
                {"grade": 1, "class": 1, "date": "2026-11-09", "period": 2, "subject": "Art", "teacher": None},
            ],
        }
        params = {
            "school": "2:Example", "week": "2026-11-09",
            "grade": 1, "class": 1, "mode": "timed", "times": "1:0900-0950",
        }
        with patch("backend.app._cached_timetable", return_value=(timetable, "hit")), \
                patch("backend.app.validate_timetable_week"):
            status, headers, body = dispatch_request("GET", "/api/v1/timetable.ics", urlencode(params))
            self.assertEqual(status, 200)
            self.assertIn("ETag", headers)
            # 09:00 KST -> 00:00 UTC
            self.assertIn(b"DTSTART:20261109T000000Z", body)
            self.assertIn(b"DTEND:20261109T005000Z", body)
            # Period 2 has no time -> fallback to all-day with explicit label
            self.assertIn(b"DTSTART;VALUE=DATE:20261109", body)
            self.assertIn("교시 시각 미설정".encode("utf-8"), body)

            # Revalidation with ETag returns 304
            status_304, _, empty_body = dispatch_request(
                "GET", "/api/v1/timetable.ics", urlencode(params),
                request_headers={"If-None-Match": headers["ETag"]},
            )
            self.assertEqual(status_304, 304)
            self.assertEqual(empty_body, b"")
        self.assertEqual(len(timetable["records"]), 2)


if __name__ == "__main__":
    unittest.main()
