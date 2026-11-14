import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from backend.app import dispatch_request


class BackendFilterContractTests(unittest.TestCase):
    def test_teacher_substring_applies_to_json_and_both_ics_modes(self):
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
            for mode in ("periods", "summary"):
                with self.subTest(mode=mode):
                    status, _, body = dispatch_request(
                        "GET", "/api/v1/timetable.ics", urlencode({**params, "mode": mode}),
                    )
                    self.assertEqual(status, 200)
                    self.assertEqual(body.count(b"BEGIN:VEVENT"), 1)
                    self.assertIn(b"Math", body)
                    self.assertNotIn(b"Science", body)
        self.assertEqual(len(timetable["records"]), 2)


if __name__ == "__main__":
    unittest.main()
