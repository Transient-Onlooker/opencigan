import csv
import io
import os
import threading
import time
import unittest
from contextlib import closing
from datetime import datetime, timezone, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

from backend.access_logs import (
    AccessLogRecorder,
    AccessLogStore,
    classify_origin,
    csv_safe_cell,
    get_access_log_store,
    normalize_origin,
    parse_kst_timestamp,
    SEOUL,
)


class AccessLogsTests(unittest.TestCase):
    def memory_store(self, retention_days=7):
        store = AccessLogStore(":memory:", retention_days=retention_days)
        self.addCleanup(store.close)
        return store

    def test_factory_off_by_default(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(get_access_log_store())
        with patch.dict(os.environ, {"OPENCIGAN_ACCESS_LOG_DB": ""}):
            self.assertIsNone(get_access_log_store())
        with patch.dict(os.environ, {"OPENCIGAN_ACCESS_LOG_DB": ":memory:"}):
            store = get_access_log_store()
            self.assertIsNotNone(store)
            self.addCleanup(store.close)

    def test_origin_normalization_and_classification(self):
        self.assertEqual(normalize_origin(None), "")
        self.assertEqual(normalize_origin(""), "")
        self.assertEqual(
            normalize_origin("https://opensigan.com/timetable?grade=1#section"),
            "https://opensigan.com",
        )
        self.assertEqual(
            normalize_origin("http://localhost:5173/"),
            "http://localhost:5173",
        )
        self.assertEqual(
            normalize_origin("https://user:pass@opensigan.com/path"),
            "https://opensigan.com",
        )

        origin_cls, ref_orig = classify_origin(None, None)
        self.assertEqual((origin_cls, ref_orig), ("unknown", ""))

        origin_cls, ref_orig = classify_origin(
            "https://opensigan.com",
            None,
            allowed_origins=["https://opensigan.com", "http://localhost:5173"],
        )
        self.assertEqual((origin_cls, ref_orig), ("frontend", "https://opensigan.com"))

        origin_cls, ref_orig = classify_origin(
            None,
            "https://evil-bot.net/crawl?q=test",
            allowed_origins=["https://opensigan.com"],
        )
        self.assertEqual((origin_cls, ref_orig), ("external", "https://evil-bot.net"))

    def test_whitelisting_and_privacy_discards_sensitive_fields(self):
        store = self.memory_store()
        long_school_id = "SCH_" + "A" * 90  # 94 chars (< 100, > 32)
        raw_event = {
            "client_ip": "203.0.113.195",
            "method": "get",
            "route": "https://user:secret@opensigan.com/api/v1/timetable?token=SECRET_AUTH_TOKEN&q=student#hash",
            "school_id": long_school_id,
            "grade": "2",
            "class_nm": "3",
            "week": "2026-W46",
            "dates": "2026-11-15",
            "datatype": "timetable",
            "status": 200,
            "duration_ms": 14.8,
            "cache_status": "HIT",
            "referrer_origin": "https://opensigan.com/secret/path?param=1",
            "origin_class": "frontend",
            "full_url": "https://opensigan.com/api/v1/timetable?token=SECRET_AUTH_TOKEN",
            "token": "BEARER_SECRET_TOKEN",
            "search_query": "private student name",
            "headers": {"Authorization": "Bearer secret"},
        }

        sanitized = store.sanitize_event(raw_event)
        self.assertNotIn("full_url", sanitized)
        self.assertNotIn("token", sanitized)
        self.assertNotIn("search_query", sanitized)
        self.assertNotIn("headers", sanitized)

        # Route stripped of scheme, credentials, query string, and hash
        self.assertEqual(sanitized["route"], "/api/v1/timetable")
        self.assertEqual(sanitized["referrer_origin"], "https://opensigan.com")
        self.assertEqual(sanitized["method"], "GET")
        self.assertEqual(sanitized["school_id"], long_school_id)

        # Missing client IP defaults to 'unknown', not 127.0.0.1
        sanitized_no_ip = store.sanitize_event({"route": "/test"})
        self.assertEqual(sanitized_no_ip["client_ip"], "unknown")

        record_id = store.record(raw_event)
        self.assertIsInstance(record_id, int)

        with closing(store._connect()) as db:
            row = dict(db.execute("SELECT * FROM access_logs WHERE id = ?", (record_id,)).fetchone())
            self.assertEqual(row["client_ip"], "203.0.113.195")
            self.assertEqual(row["route"], "/api/v1/timetable")
            self.assertEqual(row["school_id"], long_school_id)
            for col_val in row.values():
                if isinstance(col_val, str):
                    self.assertNotIn("SECRET_AUTH_TOKEN", col_val)
                    self.assertNotIn("secret@", col_val)

    def test_received_at_timestamp_preservation_and_validation(self):
        store = self.memory_store()

        # Reject naive datetime
        naive_dt = datetime(2026, 11, 15, 12, 0, 0)
        with self.assertRaises(ValueError):
            store.record({"route": "/test"}, received_at=naive_dt)

        # Accept aware datetime in UTC and convert to KST
        utc_dt = datetime(2026, 11, 15, 0, 30, 0, tzinfo=timezone.utc)
        record_id = store.record({"route": "/test"}, received_at=utc_dt)

        with closing(store._connect()) as db:
            row = dict(db.execute("SELECT timestamp, day FROM access_logs WHERE id = ?", (record_id,)).fetchone())
            self.assertEqual(row["day"], "2026-11-15")
            self.assertTrue(row["timestamp"].startswith("2026-11-15T09:30:00"))
            self.assertTrue(row["timestamp"].endswith("+09:00"))

        # Accept valid ISO string with timezone
        iso_str = "2026-11-14T23:00:00+00:00"
        rid2 = store.record({"route": "/test2"}, received_at=iso_str)
        with closing(store._connect()) as db:
            row2 = dict(db.execute("SELECT timestamp, day FROM access_logs WHERE id = ?", (rid2,)).fetchone())
            self.assertEqual(row2["day"], "2026-11-15")
            self.assertTrue(row2["timestamp"].startswith("2026-11-15T08:00:00"))

    def test_query_filters_and_boundary_validation(self):
        store = self.memory_store()
        t1 = datetime(2026, 11, 15, 10, 0, 0, tzinfo=SEOUL)
        t2 = datetime(2026, 11, 15, 11, 0, 0, tzinfo=SEOUL)

        store.record({
            "client_ip": "1.1.1.1",
            "method": "GET",
            "route": "/api/v1/timetable",
            "school_id": "SCH001",
            "grade": "1",
            "class_nm": "1",
            "status": 200,
            "duration_ms": 10.0,
            "origin_class": "frontend",
            "cache_status": "HIT",
        }, received_at=t1)

        store.record({
            "client_ip": "2.2.2.2",
            "method": "POST",
            "route": "/api/v1/meals",
            "school_id": "SCH002",
            "grade": "2",
            "class_nm": "2",
            "status": 500,
            "duration_ms": 120.0,
            "origin_class": "external",
            "cache_status": "MISS",
        }, received_at=t2)

        # Filters
        self.assertEqual(len(store.query({"client_ip": "1.1.1.1"})["items"]), 1)
        self.assertEqual(len(store.query({"school_id": "SCH002"})["items"]), 1)
        self.assertEqual(len(store.query({"grade": "2", "class_nm": "2"})["items"]), 1)
        self.assertEqual(len(store.query({"status": 500})["items"]), 1)
        self.assertEqual(len(store.query({"min_status": 400})["items"]), 1)
        self.assertEqual(len(store.query({"origin_class": "frontend"})["items"]), 1)
        self.assertEqual(len(store.query({"cache_status": "HIT"})["items"]), 1)
        self.assertEqual(len(store.query({"start_day": "2026-11-15", "end_day": "2026-11-15"})["items"]), 2)

        # Boundary validation errors
        with self.assertRaises(ValueError):
            store.query(cursor="invalid")
        with self.assertRaises(ValueError):
            store.query(cursor=-5)
        with self.assertRaises(ValueError):
            store.query({"status": 999})
        with self.assertRaises(ValueError):
            store.query({"min_status": 50})
        with self.assertRaises(ValueError):
            store.query({"start_day": "2026/11/15"})
        with self.assertRaises(ValueError):
            store.query({"origin_class": "unrecognized"})

    def test_cursor_pagination_and_max_limit_capping(self):
        store = self.memory_store()
        for i in range(120):
            store.record({
                "client_ip": f"10.0.0.{i % 250}",
                "method": "GET",
                "route": f"/api/v1/item/{i}",
                "status": 200,
            })

        # Capped at 100 max
        page1 = store.query(limit=200)
        self.assertEqual(page1["limit"], 100)
        self.assertEqual(len(page1["items"]), 100)
        self.assertTrue(page1["has_more"])
        self.assertIsNotNone(page1["next_cursor"])

        page2 = store.query(cursor=page1["next_cursor"], limit=100)
        self.assertEqual(len(page2["items"]), 20)
        self.assertFalse(page2["has_more"])
        self.assertIsNone(page2["next_cursor"])

        all_ids = [item["id"] for item in page1["items"]] + [item["id"] for item in page2["items"]]
        self.assertEqual(len(all_ids), 120)
        self.assertEqual(len(set(all_ids)), 120)

    def test_csv_safe_formula_escaping(self):
        # Escapes standard formulas
        self.assertEqual(csv_safe_cell("=CMD('calc')"), "'=CMD('calc')")
        self.assertEqual(csv_safe_cell("+123"), "'+123")
        self.assertEqual(csv_safe_cell("-456"), "'-456")
        self.assertEqual(csv_safe_cell("@SUM(A1:A10)"), "'@SUM(A1:A10)")
        self.assertEqual(csv_safe_cell("\tTAB"), "'\tTAB")
        self.assertEqual(csv_safe_cell("\rRET"), "'\rRET")
        # Escapes whitespace-prefixed formulas
        self.assertEqual(csv_safe_cell("   =SUM(A1)"), "'   =SUM(A1)")
        self.assertEqual(csv_safe_cell("  +1234"), "'  +1234")
        self.assertEqual(csv_safe_cell("normal_text"), "normal_text")
        self.assertEqual(csv_safe_cell(None), "")
        self.assertEqual(csv_safe_cell(200), "200")

        store = self.memory_store()
        store.record({
            "client_ip": "=127.0.0.1",
            "route": "/api/v1/+formula",
            "school_id": "@MALICIOUS",
            "status": 200,
        })
        csv_text = store.export_csv(limit=10)
        reader = list(csv.reader(io.StringIO(csv_text)))
        header = reader[0]
        data = reader[1]

        ip_idx = header.index("client_ip")
        sch_idx = header.index("school_id")

        self.assertTrue(data[ip_idx].startswith("'="))
        self.assertTrue(data[sch_idx].startswith("'@"))

    def test_automatic_retention_inclusive_7_days(self):
        store = self.memory_store(retention_days=7)

        # 7 inclusive days means for today 2026-11-09:
        # Keep 2026-11-03 .. 2026-11-09 (7 days).
        # Purge < 2026-11-03 (i.e. 2026-11-02 and older).
        t_old = datetime(2026, 11, 2, 12, 0, 0, tzinfo=SEOUL)
        t_edge = datetime(2026, 11, 3, 12, 0, 0, tzinfo=SEOUL)
        t_today = datetime(2026, 11, 9, 12, 0, 0, tzinfo=SEOUL)

        store.record({"client_ip": "1.1.1.1", "route": "/old"}, received_at=t_old)
        store.record({"client_ip": "2.2.2.2", "route": "/edge"}, received_at=t_edge)

        with patch.object(store, "_current_day", return_value="2026-11-09"):
            store.record({"client_ip": "3.3.3.3", "route": "/today"}, received_at=t_today)
            res = store.query()
            routes = [item["route"] for item in res["items"]]
            self.assertIn("/today", routes)
            self.assertIn("/edge", routes)
            self.assertNotIn("/old", routes)

    def test_bounded_recorder_queue_and_lifecycle(self):
        entered = threading.Event()
        release = threading.Event()

        class SlowStore:
            def record(self, event, received_at=None):
                entered.set()
                release.wait(2)

        recorder = AccessLogRecorder(lambda: SlowStore(), capacity=1)
        self.addCleanup(recorder.close)

        try:
            # First submit starts worker and holds lock in SlowStore
            self.assertTrue(recorder.submit({"client_ip": "1.1.1.1"}))
            self.assertTrue(entered.wait(1))
            # Second submit fills queue capacity (1)
            self.assertTrue(recorder.submit({"client_ip": "2.2.2.2"}))
            # Third submit must drop without blocking
            self.assertFalse(recorder.submit({"client_ip": "3.3.3.3"}))
            self.assertEqual(recorder.dropped, 1)
        finally:
            release.set()
            self.assertTrue(recorder.flush(timeout=2.0))
            self.assertTrue(recorder.close(timeout=2.0))

    def test_full_queue_close_timeout_still_exits_after_draining(self):
        entered, release = threading.Event(), threading.Event()
        class SlowStore:
            def record(self, event, received_at=None):
                entered.set()
                release.wait(2)
        recorder = AccessLogRecorder(lambda: SlowStore(), capacity=1)
        self.addCleanup(recorder.close)
        try:
            recorder.submit({'client_ip': '1.1.1.1'})
            self.assertTrue(entered.wait(1))
            recorder.submit({'client_ip': '2.2.2.2'})
            self.assertFalse(recorder.close(timeout=0.01))
            self.assertFalse(recorder.submit({'client_ip': '3.3.3.3'}))
        finally:
            release.set()
        self.assertTrue(recorder.flush(timeout=2))
        self.assertTrue(recorder.close(timeout=2))


if __name__ == "__main__":
    unittest.main()

