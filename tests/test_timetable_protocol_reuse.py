import unittest
from types import SimpleNamespace
from unittest.mock import patch

from backend import timetable


class ProtocolReuseTests(unittest.TestCase):
    def setUp(self):
        self.protocol = object()
        self.saved = (timetable._protocol, timetable._protocol_content, timetable._protocol_expires,
                      timetable._verified_schools.copy())
        timetable._protocol = self.protocol
        timetable._protocol_content = "fixture service page"
        timetable._protocol_expires = 1000
        timetable._verified_schools.clear()
        self.addCleanup(self.restore)

    def restore(self):
        timetable._protocol, timetable._protocol_content, timetable._protocol_expires, schools = self.saved
        timetable._verified_schools.clear()
        timetable._verified_schools.update(schools)

    def test_unique_search_reuses_protocol_and_preserves_original_lessons(self):
        events = []
        original = SimpleNamespace(subject="Before", teacher="Teacher A")
        lesson = SimpleNamespace(subject="After", teacher="Teacher B", period=1, replaced=True, original=original)

        class FakeTimeTable:
            def __init__(self, *args, **kwargs):
                events.append("fallback")
                self._initialize_from_data({}, 3, "School", 42, ())

            @staticmethod
            def _get_comcigan_codes(content):
                events.append("codes")
                return (content,)

            @staticmethod
            def _fetch_timetable_data(code, week, codes, protocol):
                events.append(("upstream", code, week, protocol))
                return {}

            def _initialize_from_data(self, data, local_code, school_name, school_code, codes):
                self.timetable = [[], [[], [[], [lesson]]]]
                self.update_date = None

        with patch.object(timetable.time, "monotonic", return_value=100), \
             patch.object(timetable, "configure_comcigan_proxy"), \
             patch.object(timetable, "validate_timetable_week", return_value=0), \
             patch.object(timetable, "_search_with_cached_protocol", return_value=([[3, "Region", "School", 42]], self.protocol)), \
             patch("pycomcigan.TimeTable", FakeTimeTable):
            timetable.search_schools("School")
            public = timetable.fetch_timetable("42:School", "2026-11-23")
            internal = timetable.fetch_timetable("42:School", "2026-11-23", include_original=True)
        self.assertEqual(events, ["codes", ("upstream", 42, 0, self.protocol)] * 2)
        self.assertEqual(public["records"][0]["subject"], "After")
        self.assertNotIn("originalSubject", public["records"][0])
        self.assertEqual(internal["records"][0]["originalSubject"], "Before")
        self.assertEqual(internal["records"][0]["originalTeacher"], "Teacher A")

    def test_ambiguous_search_does_not_cache_school_identity(self):
        for second_name in ("School", "School Annex"):
            rows = [[3, "A", "School", 42], [4, "B", second_name, 42]]
            with self.subTest(second_name=second_name), \
                 patch.object(timetable.time, "monotonic", return_value=100), \
                 patch.object(timetable, "_search_with_cached_protocol", return_value=(rows, self.protocol)):
                timetable.search_schools("School")
                self.assertNotIn("42:School", timetable._verified_schools)

    def test_authentication_failure_invalidates_protocol_and_retries_once(self):
        calls = []

        class FakeTimeTable:
            def __init__(self, *args, **kwargs):
                calls.append("fallback")
                self.timetable = []
                self.update_date = None

            @staticmethod
            def _get_comcigan_codes(content):
                return ()

            @staticmethod
            def _fetch_timetable_data(*args):
                calls.append("fast")
                raise RuntimeError("Encrypted response authentication failed")

        timetable._verified_schools["42:School"] = (3, 1000)
        with patch.object(timetable.time, "monotonic", return_value=100), \
             patch.object(timetable, "configure_comcigan_proxy"), \
             patch.object(timetable, "validate_timetable_week", return_value=0), \
             patch("pycomcigan.TimeTable", FakeTimeTable):
            result = timetable.fetch_timetable("42:School", "2026-11-23")
        self.assertEqual(calls, ["fast", "fallback"])
        self.assertIsNone(timetable._protocol)
        self.assertEqual(result["records"], [])

    def test_real_parser_matches_baseline_with_one_timetable_fetch(self):
        from pycomcigan import TimeTable

        codes = ("endpoint", "prefix", "teachers", "subjects", "updated", "current", "original")
        teachers = [""] * 124
        teachers[122], teachers[123] = "Teacher A", "Teacher B"
        subjects = [""] * 9
        subjects[7], subjects[8] = "After", "Before"
        data = {
            "지역명": "Region", "학년도": 2026, "시작일": "2026-11-23", "일과시간": [],
            "updated": "2026-11-23 08:00", "teachers": teachers, "subjects": subjects,
            "current": [[], [[], [1, [1, ">7123"]]]],
            "original": [[], [[], [1, [1, 8122]]]], "담임": [], "분리": 1000, "변경알림": 1,
        }
        with patch.object(timetable.time, "monotonic", return_value=100), \
             patch.object(timetable, "configure_comcigan_proxy"), \
             patch.object(timetable, "validate_timetable_week", return_value=0), \
             patch("pycomcigan.timetable.get_comcigan_response_for_codes", return_value=SimpleNamespace(text="page")) as page, \
             patch("pycomcigan.timetable.decode_service_page", return_value="page"), \
             patch("pycomcigan.timetable.parse_service_protocol", return_value=self.protocol), \
             patch.object(TimeTable, "_get_comcigan_codes", return_value=codes), \
             patch.object(TimeTable, "_resolve_school", return_value=(3, "School", 42)) as resolve, \
             patch.object(TimeTable, "_fetch_timetable_data", return_value=data) as fetch:
            baseline = timetable.fetch_timetable("42:School", "2026-11-23", include_original=True)
            self.assertEqual((page.call_count, resolve.call_count, fetch.call_count), (1, 1, 1))
            timetable._verified_schools["42:School"] = (3, 1000)
            fast = timetable.fetch_timetable("42:School", "2026-11-23", include_original=True)
            self.assertEqual((page.call_count, resolve.call_count, fetch.call_count), (1, 1, 2))
        baseline.pop("fetchedAt")
        fast.pop("fetchedAt")
        self.assertEqual(fast, baseline)
        self.assertEqual(fast["records"][0]["originalSubject"], "Before")

    def test_expired_or_unverified_identity_uses_existing_lookup(self):
        calls = []

        class FakeTimeTable:
            def __init__(self, *args, **kwargs):
                calls.append((args, kwargs))
                self.timetable = []
                self.update_date = None

        with patch.object(timetable.time, "monotonic", return_value=100), \
             patch.object(timetable, "configure_comcigan_proxy"), \
             patch.object(timetable, "validate_timetable_week", return_value=0), \
             patch("pycomcigan.TimeTable", FakeTimeTable):
            timetable.fetch_timetable("42:School", "2026-11-23")
            timetable._verified_schools["42:School"] = (3, 99)
            timetable.fetch_timetable("42:School", "2026-11-23")
        self.assertEqual(len(calls), 2)
        self.assertTrue(all(kwargs == {"school_code": 42, "week_num": 0} for _, kwargs in calls))

    def test_rate_limit_does_not_retry(self):
        class FakeTimeTable:
            def __init__(self, *args, **kwargs):
                raise AssertionError("unexpected fallback")

            @staticmethod
            def _get_comcigan_codes(content):
                return ()

            @staticmethod
            def _fetch_timetable_data(*args):
                raise RuntimeError("Comcigan rate limit reached (HTTP 429); retry later")

        timetable._verified_schools["42:School"] = (3, 1000)
        with patch.object(timetable.time, "monotonic", return_value=100), \
             patch.object(timetable, "configure_comcigan_proxy"), \
             patch.object(timetable, "validate_timetable_week", return_value=0), \
             patch("pycomcigan.TimeTable", FakeTimeTable):
            with self.assertRaisesRegex(RuntimeError, "429"):
                timetable.fetch_timetable("42:School", "2026-11-23")
        self.assertIs(timetable._protocol, self.protocol)

    def test_search_from_invalidated_protocol_does_not_verify_identity(self):
        def search(*args, **kwargs):
            timetable._protocol = object()
            return [[3, "Region", "School", 42]], self.protocol

        with patch.object(timetable.time, "monotonic", return_value=100), \
             patch.object(timetable, "_search_with_cached_protocol", side_effect=search):
            self.assertEqual(timetable.search_schools("School")[0]["id"], "42:School")
        self.assertNotIn("42:School", timetable._verified_schools)

    def test_403_invalidates_identity_without_immediate_retry(self):
        class FakeTimeTable:
            def __init__(self, *args, **kwargs):
                raise AssertionError("unexpected fallback")

            @staticmethod
            def _get_comcigan_codes(content):
                return ()

            @staticmethod
            def _fetch_timetable_data(*args):
                raise RuntimeError("Comcigan request rejected (HTTP 403); the page token may have expired")

        timetable._verified_schools["42:School"] = (3, 1000)
        with patch.object(timetable.time, "monotonic", return_value=100), \
             patch.object(timetable, "configure_comcigan_proxy"), \
             patch.object(timetable, "validate_timetable_week", return_value=0), \
             patch("pycomcigan.TimeTable", FakeTimeTable):
            with self.assertRaisesRegex(RuntimeError, "403"):
                timetable.fetch_timetable("42:School", "2026-11-23")
        self.assertIsNone(timetable._protocol)
        self.assertEqual(timetable._verified_schools, {})
