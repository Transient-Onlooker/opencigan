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
            received_at = event.pop("received_at", iso_hours_ago(hours_ago))
            event.setdefault("route", "/api/v1/timetable")
            event.setdefault("client_ip", "203.0.113.1")
            event.setdefault("status", 200)
            event.setdefault("duration_ms", 10.0)
            event.setdefault("origin_class", "external")
            self.store.record(event, received_at=received_at)

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
        for _ in range(6):
            self.rec(48, client_ip="198.51.100.9", status=500)

        findings = detect(self.store._connect(), window_hours=24, max_requests_per_ip=5, max_error_ratio=0.5, max_distinct_schools=50, min_requests=0)
        self.assertEqual([f["client_ip"] for f in findings if f["kind"] == "request_volume"], ["203.0.113.1"])
        self.assertNotIn("198.51.100.9", {f["client_ip"] for f in findings})

    def test_first_and_last_seen_follow_receipt_time_not_insert_order(self):
        whole_second = (datetime.now(tz=SEOUL) - timedelta(hours=1)).replace(microsecond=0)
        later = whole_second.replace(microsecond=500000)
        self.rec(1, received_at=later, school_id="school-a", status=429)
        self.rec(1, received_at=whole_second, school_id="school-a", status=200)
        self.rec(1, received_at=whole_second, school_id="school-b", status=500)

        findings = self.store.review_anomalies(
            window_hours=24, max_requests_per_ip=2,
            max_error_ratio=0.5, max_distinct_schools=1, min_requests=3,
        )
        self.assertEqual([f["kind"] for f in findings], [
            "request_volume", "error_ratio", "school_scan",
        ])
        for finding in findings:
            self.assertEqual(finding["first_seen"], whole_second.isoformat())
            self.assertEqual(finding["last_seen"], later.isoformat())
            self.assertEqual(finding["errors"], 2)
        self.assertEqual(findings[2]["observed"], 2)

    def test_review_respects_retention_and_does_not_group_unknown_clients(self):
        for _ in range(3):
            self.rec(48, client_ip="198.51.100.9", status=500)
            self.rec(0, client_ip="unknown", status=500)
        self.store.retention_days = 1
        findings = self.store.review_anomalies(
            window_hours=720, max_requests_per_ip=1,
            max_error_ratio=0.5, max_distinct_schools=50, min_requests=1,
        )
        self.assertEqual(findings, [])

    def test_exact_thresholds_and_distinct_ip_are_not_flagged(self):
        for ip in ("203.0.113.1", "203.0.113.2"):
            self.rec(0, client_ip=ip, school_id="school-a", status=404)
            self.rec(0, client_ip=ip, school_id="school-a", status=200)
        findings = self.store.review_anomalies(
            window_hours=24, max_requests_per_ip=2,
            max_error_ratio=0.5, max_distinct_schools=1, min_requests=2,
        )
        self.assertEqual(findings, [])

    def test_opt_in_status_groups_are_isolated_and_respect_threshold_and_window(self):
        for status in (404, 404, 429, 429, 500, 503, 200):
            self.rec(1, status=status)
        self.rec(1, client_ip='203.0.113.2', status=404)
        self.rec(48, status=404)
        self.rec(1, client_ip='unknown', status=404)
        self.rec(1, client_ip='unknown', status=404)
        kwargs = dict(window_hours=24, max_requests_per_ip=1000,
                      max_error_ratio=1.0, max_distinct_schools=50, min_requests=0)
        self.assertEqual(self.store.review_anomalies(**kwargs), [])
        findings = self.store.review_anomalies(**kwargs, max_status_errors=1)
        self.assertEqual([(item['client_ip'], item['status_group'], item['observed']) for item in findings], [
            ('203.0.113.1', '404', 2), ('203.0.113.1', '429', 2), ('203.0.113.1', '5xx', 2),
        ])
        self.assertEqual(self.store.review_anomalies(**kwargs, max_status_errors=2), [])
        kwargs['min_requests'] = 8
        self.assertEqual(self.store.review_anomalies(**kwargs, max_status_errors=1), [])


class QueryAnomalyEndpointTests(unittest.TestCase):
    def setUp(self):
        from backend.access_logs import AccessLogStore

        self.store = AccessLogStore(":memory:")
        self.store.record({"timestamp": iso_hours_ago(0), "day": "2026-11-24", "client_ip": "203.0.113.1", "route": "/api/v1/timetable", "status": 200, "duration_ms": 1.0, "origin_class": "external"})
        self.addCleanup(self.store.close)

        self.patches = [
            patch.dict("os.environ", {"OPENCIGAN_ACCESS_LOG_DB": "test", "OPENCIGAN_ADMIN_TOKEN": "secret", "OPENCIGAN_ACCESS_LOG_RETENTION_DAYS": "7"}),
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
        for query in ("window_hours=0", "window_hours=x", "max_requests_per_ip=0", "max_error_ratio=2", "max_status_errors=0", "max_status_errors=1&max_status_errors=2", "unknown=1"):
            with self.subTest(query=query):
                status, _, body = dispatch_request("GET", "/api/v1/admin/access-anomalies", query, request_headers=auth)
                self.assertEqual(status, 400)
                self.assertTrue(__import__("json").loads(body)["code"])

    def test_endpoint_status_review_is_explicit_and_authenticated(self):
        from backend.app import dispatch_request
        for status in (429, 429):
            self.store.record({"client_ip": "203.0.113.1", "route": "/api/v1/timetable", "status": status, "duration_ms": 1.0, "origin_class": "external"})
        path = "/api/v1/admin/access-anomalies"
        self.assertEqual(dispatch_request("GET", path, "max_status_errors=1")[0], 401)
        status, _, body = dispatch_request("GET", path, "max_status_errors=1&min_requests=1", request_headers={"Authorization": "Bearer secret"})
        payload = __import__("json").loads(body)
        self.assertEqual(status, 200)
        self.assertEqual(payload['thresholds']['max_status_errors'], 1)
        self.assertEqual([(row['status_group'], row['observed']) for row in payload['findings'] if row['kind'] == 'status_errors'], [('429', 2)])

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
             patch.dict("os.environ", {"OPENCIGAN_ACCESS_LOG_DB": "test", "OPENCIGAN_ADMIN_TOKEN": "secret"}):
            status, _, body = dispatch_request("GET", "/api/v1/admin/access-anomalies", "", request_headers=auth)
            self.assertEqual(status, 503)
            self.assertEqual(__import__("json").loads(body)["code"], "access_logs_disabled")
