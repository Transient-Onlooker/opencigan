import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch


SEOUL = timezone(timedelta(hours=9))


def iso_hours_ago(hours: float) -> str:
    return (datetime.now(tz=SEOUL) - timedelta(hours=hours)).isoformat()


class QueryAnomalyTests(unittest.TestCase):
    def setUp(self):
        from backend.access_logs import AccessLogStore

        self.store = AccessLogStore(":memory:")

        def rec(hours_ago, **event):
            event.setdefault("timestamp", iso_hours_ago(hours_ago))
            event.setdefault("day", datetime.now(tz=SEOUL).date().isoformat())
            event.setdefault("route", "/api/v1/timetable")
            event.setdefault("client_ip", "203.0.113.1")
            event.setdefault("status", 200)
            event.setdefault("duration_ms", 10.0)
            event.setdefault("origin_class", "external")
            self.store.record(event)

        self.rec = rec

    def tearDown(self):
        self.store.close()

    def test_no_findings_on_quiet_log(self):
        from backend.query_anomalies import detect

        self.rec(1)

        findings = detect(self.store._connect(), window_hours=24, max_requests_per_ip=1000, max_error_ratio=0.5, max_distinct_schools=50, min_requests=20)
        self.assertEqual(findings, [])

    def test_request_volume_finding(self):
        from backend.query_anomalies import detect

        for _ in range(12):
            self.rec(1)

        findings = detect(self.store._connect(), window_hours=24, max_requests_per_ip=5, max_error_ratio=0.5, max_distinct_schools=50, min_requests=0)
        kinds = [f["kind"] for f in findings]
        self.assertIn("request_volume", kinds)

    def test_error_ratio_finding_needs_min_requests(self):
        from backend.query_anomalies import detect

        self.rec(1, status=500)

        without_min = detect(self.store._connect(), window_hours=24, max_requests_per_ip=1000, max_error_ratio=0.5, max_distinct_schools=50, min_requests=20)
        self.assertEqual([f["kind"] for f in without_min], [])

        with_min = detect(self.store._connect(), window_hours=24, max_requests_per_ip=1000, max_error_ratio=0.5, max_distinct_schools=50, min_requests=1)
        self.assertEqual([f["kind"] for f in with_min], ["error_ratio"])

    def test_school_scan_finding(self):
        from backend.query_anomalies import detect

        for index in range(60):
            self.rec(1, school_id=f"{index}:school", route=f"/api/v1/timetable?school={index}:{index}")

        findings = detect(self.store._connect(), window_hours=24, max_requests_per_ip=1000, max_error_ratio=0.5, max_distinct_schools=50, min_requests=20)
        kinds = [f["kind"] for f in findings]
        self.assertIn("school_scan", kinds)

    def test_window_excludes_older_rows(self):
        from backend.query_anomalies import detect

        for _ in range(20):
            self.rec(1)
        self.rec(48, client_ip="198.51.100.9", status=500)

        findings = detect(self.store._connect(), window_hours=24, max_requests_per_ip=5, max_error_ratio=0.5, max_distinct_schools=50, min_requests=0)
        self.assertEqual([f["client_ip"] for f in findings if f["kind"] == "request_volume"], ["203.0.113.1"])


class QueryAnomalyEndpointTests(unittest.TestCase):
    def setUp(self):
        from backend.access_logs import AccessLogStore

        self.store = AccessLogStore(":memory:")
        self.store.record({"timestamp": iso_hours_ago(0), "day": "2026-11-24", "client_ip": "203.0.113.1", "route": "/api/v1/timetable", "status": 200, "duration_ms": 1.0, "origin_class": "external"})
        self.addCleanup(self.store.close)

        self.patches = [
            patch.dict("os.environ", {"OPENCIGAN_ACCESS_LOG_DB": "test", "OPENCIGAN_ACCESS_LOG_ADMIN_TOKEN": "secret", "OPENCIGAN_ACCESS_LOG_RETENTION_DAYS": "7"}),
            patch("backend.app._access_log_store", return_value=self.store),
        ]
        for p in self.patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in self.patches])

    def test_endpoint_contract(self):
        from backend.app import dispatch_request

        auth = {"Authorization": "Bearer secret"}
        status, headers, body = dispatch_request("GET", "/api/v1/admin/access-anomalies", "window_hours=24", request_headers=auth)
        self.assertEqual(status, 200)
        payload = __import__("json").loads(body)
        self.assertEqual(payload["window_hours"], 24)
        self.assertIn("findings", payload)

    def test_endpoint_rejects_bad_values(self):
        from backend.app import dispatch_request

        auth = {"Authorization": "Bearer secret"}
        for query in ("window_hours=0", "window_hours=x", "max_requests_per_ip=0", "max_error_ratio=2", "unknown=1"):
            with self.subTest(query=query):
                status, _, body = dispatch_request("GET", "/api/v1/admin/access-anomalies", query, request_headers=auth)
                self.assertEqual(status, 400)
                self.assertTrue(__import__("json").loads(body)["code"])

    def test_endpoint_requires_admin_auth(self):
        from backend.app import dispatch_request

        status, _, _ = dispatch_request("GET", "/api/v1/admin/access-anomalies", "")
        self.assertEqual(status, 401)

        status, _, _ = dispatch_request("GET", "/api/v1/admin/access-anomalies", "", request_headers={"Authorization": "Bearer wrong"})
        self.assertEqual(status, 401)

    def test_endpoint_method_and_store_errors(self):
        from backend.app import dispatch_request

        auth = {"Authorization": "Bearer secret"}
        status, _, _ = dispatch_request("POST", "/api/v1/admin/access-anomalies", "", request_headers=auth)
        self.assertEqual(status, 405)

        with patch("backend.app._access_log_store", return_value=None), \
             patch.dict("os.environ", {"OPENCIGAN_ACCESS_LOG_DB": "test", "OPENCIGAN_ACCESS_LOG_ADMIN_TOKEN": "secret"}):
            status, _, body = dispatch_request("GET", "/api/v1/admin/access-anomalies", "", request_headers=auth)
            self.assertEqual(status, 503)
            self.assertEqual(__import__("json").loads(body)["code"], "access_logs_disabled")
