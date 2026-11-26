import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from urllib.parse import urlencode

import yaml
from jsonschema import Draft202012Validator, FormatChecker

from backend.app import _rate_clients, dispatch_request
from backend.cache import Cache
from backend.webhook_store import SubscriptionLimitError


class OpenApiContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = Path(__file__).resolve().parents[1] / "docs" / "openapi.yaml"
        cls.spec = yaml.safe_load(path.read_text(encoding="utf-8"))
        cls.start = datetime.now(timezone(timedelta(hours=9))).date()
        cls.start -= timedelta(days=cls.start.weekday())

    def setUp(self):
        _rate_clients.clear()
        self.cache = Cache()

    def response_schema(self, path, status, media_type):
        response = self.spec["paths"][path]["get"]["responses"][str(status)]
        if "$ref" in response:
            response = self.spec["components"]["responses"][response["$ref"].rsplit("/", 1)[-1]]
        return response["content"][media_type]["schema"]

    def assert_json_response(self, path, status, headers, body):
        self.assertTrue(headers["Content-Type"].startswith("application/json"))
        schema = self.response_schema(path, status, "application/json")
        validator = Draft202012Validator({"$ref": "#/$defs/response", "$defs": {"response": schema},
                                         "components": self.spec["components"]}, format_checker=FormatChecker())
        validator.validate(json.loads(body))

    def test_status_documents_gateway_errors_and_retry_header(self):
        operation = self.spec['paths']['/api/v1/status']['get']
        self.assertIn('429', operation['responses'])
        self.assertIn('503', operation['responses'])
        response = self.spec['components']['responses']['TooManyRequests']
        self.assertIn('Retry-After', response['headers'])
        for status, code in ((429, 'edge_rate_limited'), (503, 'gateway_unavailable'), (503, 'gateway_unconfigured')):
            schema = self.response_schema('/api/v1/status', status, 'application/json')
            validator = Draft202012Validator({'$ref': '#/$defs/response', '$defs': {'response': schema},
                                             'components': self.spec['components']})
            validator.validate({'code': code, 'error': 'unavailable', 'message': 'unavailable'})

    def test_school_query_validation_matches_openapi(self):
        for path in ('/api/v1/schools', '/api/v1/neis/schools'):
            schema = self.spec['paths'][path]['get']['parameters'][0]['schema']
            validator = Draft202012Validator(schema)
            for value in ('', '   ', 'x' * 51):
                with self.subTest(path=path, value=value):
                    self.assertFalse(validator.is_valid(value))
                    status, headers, body = dispatch_request('GET', path, urlencode({'q': value}), cache_instance=Cache())
                    self.assertEqual(status, 400)
                    self.assert_json_response(path, status, headers, body)
            self.assertTrue(validator.is_valid('  school  '))

    def test_meal_query_accepts_existing_date_formats_and_decimal_codes(self):
        path = '/api/v1/meals'
        cases = (
            {'school': 'B１０:1234567', 'from': '2026-11-16', 'to': '2026-11-16'},
            {'school': 'B10:1234567', 'from': '20261116', 'to': '2026-11-16'},
            {'school': 'B10:1234567', 'from': '2026-W47-1', 'to': '20261116'},
        )
        schemas = {param['name']: param['schema'] for param in self.spec['paths'][path]['get']['parameters']}
        with patch.dict('os.environ', {'NEIS_API_KEY': 'synthetic'}), \
             patch('backend.app.NEISClient') as client:
            client.from_environment.return_value.get_meals.return_value = []
            for params in cases:
                with self.subTest(params=params):
                    for name, value in params.items():
                        Draft202012Validator(schemas[name]).validate(value)
                    status, headers, body = dispatch_request('GET', path, urlencode(params), cache_instance=Cache())
                    self.assertEqual(status, 200)
                    self.assert_json_response(path, status, headers, body)

    def test_admin_access_anomaly_responses_match_openapi(self):
        from backend.access_logs import AccessLogStore

        path = '/api/v1/admin/access-anomalies'
        parameters = {parameter['name']: parameter for parameter in self.spec['paths'][path]['parameters']}
        self.assertEqual(set(parameters), {
            'window_hours', 'max_requests_per_ip', 'max_error_ratio',
            'max_distinct_schools', 'min_requests', 'max_status_errors',
        })
        auth = {'Authorization': 'Bearer synthetic-admin-token'}
        store = AccessLogStore(':memory:')
        self.addCleanup(store.close)
        observed_at = datetime.now(timezone(timedelta(hours=9)))
        synthetic_requests = (
            [('192.0.2.10', 429 if index < 3 else 200, None) for index in range(20)]
            + [('198.51.100.10', 200, None) for _ in range(21)]
            + [('203.0.113.10', 400 if index < 8 else 200, None) for index in range(20)]
            + [('192.0.2.20', 200, '1:Synthetic A' if index < 10 else '1:Synthetic B') for index in range(20)]
        )
        for index, (client_ip, response_status, school_id) in enumerate(synthetic_requests):
            store.record(
                {
                    'client_ip': client_ip,
                    'route': '/api/v1/timetable',
                    'status': response_status,
                    'duration_ms': 1.0,
                    'origin_class': 'external',
                    'school_id': school_id,
                },
                received_at=observed_at - timedelta(minutes=index),
            )
        query = urlencode({
            'window_hours': 12,
            'max_requests_per_ip': 20,
            'max_error_ratio': 0.3,
            'max_distinct_schools': 1,
            'min_requests': 20,
            'max_status_errors': 2,
        })
        with (
            patch.dict('os.environ', {'OPENCIGAN_ADMIN_TOKEN': 'synthetic-admin-token'}),
            patch('backend.app._access_log_store', return_value=store),
        ):
            status, headers, body = dispatch_request('GET', path, query, request_headers=auth)

        self.assertEqual(status, 200)
        self.assertEqual(headers['Cache-Control'], 'no-store')
        self.assert_json_response(path, status, headers, body)
        response_schema = self.response_schema(path, 200, 'application/json')
        Draft202012Validator(
            {'$ref': '#/$defs/response', '$defs': {'response': response_schema},
             'components': self.spec['components']},
            format_checker=FormatChecker(),
        ).validate(self.spec['paths'][path]['get']['responses']['200']['content']['application/json']['example'])
        payload = json.loads(body)
        self.assertEqual(payload['window_hours'], 12)
        self.assertEqual(payload['thresholds'], {
            'max_requests_per_ip': 20,
            'max_error_ratio': 0.3,
            'max_distinct_schools': 1,
            'min_requests': 20,
            'max_status_errors': 2,
        })
        findings_by_kind = {}
        for finding in payload['findings']:
            findings_by_kind.setdefault(finding['kind'], []).append(finding)
        self.assertEqual(set(findings_by_kind), {
            'status_errors', 'request_volume', 'error_ratio', 'school_scan',
        })
        status_finding = next(
            finding for finding in findings_by_kind['status_errors']
            if finding['status_group'] == '429'
        )
        self.assertEqual(status_finding['client_ip'], '192.0.2.10')
        self.assertEqual(
            (status_finding['observed'], status_finding['threshold'], status_finding['requests']),
            (3, 2, 20),
        )
        documented_finding = self.spec['paths'][path]['get']['responses']['200']['content']['application/json']['example']['findings'][0]
        self.assertEqual(
            (documented_finding['kind'], documented_finding['observed'], documented_finding['threshold'], documented_finding['requests']),
            (status_finding['kind'], status_finding['observed'], status_finding['threshold'], status_finding['requests']),
        )

    def test_admin_access_anomaly_error_responses_match_openapi(self):
        path = '/api/v1/admin/access-anomalies'
        auth = {'Authorization': 'Bearer synthetic-admin-token'}
        with patch.dict('os.environ', {'OPENCIGAN_ADMIN_TOKEN': 'synthetic-admin-token'}):
            cases = (
                ('GET', 'max_error_ratio=0', auth, 400, None),
                ('GET', '', {}, 401, None),
                ('GET', '', auth, 503, None),
                ('GET', '', auth, 503, Mock(review_anomalies=Mock(side_effect=OSError('synthetic storage failure')))),
            )
            for method, query, request_headers, expected, store in cases:
                with self.subTest(status=expected, store_failure=store is not None):
                    with patch('backend.app._access_log_store', return_value=store):
                        status, headers, body = dispatch_request(
                            method, path, query, request_headers=request_headers
                        )
                    self.assertEqual(status, expected)
                    self.assert_json_response(path, status, headers, body)
                    self.assertIn(json.loads(body)['code'], {
                        400: {'invalid_request'},
                        401: {'unauthorized'},
                        503: {'access_logs_disabled', 'access_logs_unavailable'},
                    }[expected])

    def test_retry_after_headers_allow_sdk_supported_values(self):
        cases = (
            ('TooManyRequests', '30'),
            ('UpstreamUnavailable', 'Wed, 25 Nov 2026 12:00:00 GMT'),
        )
        for response_name, retry_after in cases:
            with self.subTest(response=response_name, retry_after=retry_after):
                schema = self.spec['components']['responses'][response_name]['headers']['Retry-After']['schema']
                Draft202012Validator(schema).validate(retry_after)

    def test_search_backoff_503_documents_retry_after(self):
        path = '/api/v1/schools'
        with patch('backend.app.search_schools', side_effect=TimeoutError('private upstream detail')):
            status, headers, body = dispatch_request('GET', path, urlencode({'q': '예시'}), self.cache)
        self.assertEqual(status, 503)
        self.assertGreaterEqual(int(headers['Retry-After']), 1)
        self.assertIn('Retry-After', self.spec['components']['responses']['UpstreamUnavailable']['headers'])
        self.assert_json_response(path, status, headers, body)
        self.assertEqual(json.loads(body)['code'], 'upstream_unavailable')
        self.assertNotIn('private upstream detail', body.decode('utf-8'))

    def test_filtered_timetable_and_invalid_input_follow_schema(self):
        path = "/api/v1/timetable"
        week = self.start.isoformat()
        records = [dict(grade=2, date=week, period=1, subject="수학", teacher="김교사", isChanged=False, **{"class": room})
                   for room in (3, 4)]
        source = {"schoolId": "2:예시학교", "weekStart": week, "records": records,
                  "sourceUpdatedAt": None, "fetchedAt": "2026-11-14T00:00:00Z", "stale": False,
                  "sourceLessonStarts": {"1": "09:10", "2": "10:10"}}
        params = {"school": source["schoolId"], "week": week, "grade": "2", "class": "3", "teacher": "김"}
        with patch("backend.app.fetch_timetable", return_value=source):
            status, headers, body = dispatch_request("GET", path, urlencode(params), self.cache)
        self.assertEqual(status, 200)
        self.assert_json_response(path, status, headers, body)
        self.assertEqual(json.loads(body)["records"], records[:1])
        self.assertEqual(json.loads(body)["sourceLessonStarts"], source["sourceLessonStarts"])
        status, headers, body = dispatch_request("GET", path, urlencode(params), self.cache)
        self.assert_json_response(path, status, headers, body)
        self.assertEqual(json.loads(body)["sourceLessonStarts"], source["sourceLessonStarts"])
        self.assertEqual(json.loads(body)["cacheStatus"], "hit")
        params["grade"] = "7"
        status, headers, body = dispatch_request("GET", path, urlencode(params), self.cache)
        self.assertEqual(status, 400)
        self.assert_json_response(path, status, headers, body)
        parameters = {p["name"]: p for p in self.spec["paths"][path]["get"]["parameters"]}
        for key, value in (("grade", 2), ("class", 3), ("teacher", "김")):
            Draft202012Validator(parameters[key]["schema"]).validate(value)
        self.assertFalse(Draft202012Validator(parameters["grade"]["schema"]).is_valid(7))

    def test_history_unavailable_responses_match_documented_examples(self):
        path = "/api/v1/timetable/history"
        query = urlencode({"school": "2:예시학교", "week": self.start.isoformat()})
        examples = self.spec["paths"][path]["get"]["responses"]["503"]["content"]["application/json"]["examples"]
        for store, example in ((None, "disabled"), (Mock(list=Mock(side_effect=OSError("storage"))), "unavailable")):
            with self.subTest(example=example), patch("backend.app._history_store", return_value=store):
                status, headers, body = dispatch_request("GET", path, query, self.cache)
                self.assertEqual(status, 503)
                self.assert_json_response(path, status, headers, body)
                self.assertEqual(json.loads(body), examples[example]["value"])

    def test_history_rss_unavailable_responses_match_documented_examples(self):
        path = "/api/v1/timetable/history.rss"
        query = urlencode({"school": "2:예시학교", "grade": 2, "class": 3, "week": self.start.isoformat()})
        examples = self.spec["paths"][path]["get"]["responses"]["503"]["content"]["application/json"]["examples"]
        for store, example in ((None, "disabled"), (Mock(list=Mock(side_effect=OSError("storage"))), "unavailable")):
            with self.subTest(example=example), patch("backend.app._history_store", return_value=store):
                status, headers, body = dispatch_request("GET", path, query, self.cache)
                self.assertEqual(status, 503)
                self.assert_json_response(path, status, headers, body)
                self.assertEqual(json.loads(body), examples[example]["value"])

    def test_webhook_create_unavailable_responses_match_documented_examples(self):
        path = "/api/v1/webhooks"
        examples = self.spec["paths"][path]["post"]["responses"]["503"]["content"]["application/json"]["examples"]
        payload = json.dumps({"school": "2:예시학교", "grade": 2, "class": 3,
                              "destination": "https://discord.com/api/webhooks/123/secret"}).encode()
        for store, example in ((None, "disabled"),
                               (Mock(create=Mock(side_effect=SubscriptionLimitError())), "limit"),
                               (Mock(create=Mock(side_effect=OSError("private storage detail"))), "unavailable")):
            with self.subTest(example=example), patch("backend.app._webhook_store", return_value=store):
                status, headers, body = dispatch_request("POST", path, "", self.cache, request_body=payload)
                self.assertEqual(status, 503)
                self.assertTrue(headers["Content-Type"].startswith("application/json"))
                schema = self.spec["paths"][path]["post"]["responses"]["503"]["content"]["application/json"]["schema"]
                Draft202012Validator({"$ref": "#/$defs/response", "$defs": {"response": schema},
                                      "components": self.spec["components"]}).validate(json.loads(body))
                self.assertEqual(json.loads(body), examples[example]["value"])
                self.assertNotIn("private storage detail", body.decode())

    def test_other_read_endpoints_follow_response_schemas(self):
        path = "/api/v1/status"
        status, headers, body = dispatch_request("GET", path, "")
        self.assertEqual(status, 200)
        self.assert_json_response(path, status, headers, body)

        path = "/api/v1/schools"
        with patch("backend.app.search_schools", return_value=[{"id": "2:예시학교", "name": "예시학교", "region": "서울"}]):
            status, headers, body = dispatch_request("GET", path, "q=example", self.cache)
        self.assertEqual(status, 200)
        self.assert_json_response(path, status, headers, body)

        neis = Mock()
        neis.search_schools.return_value = [SimpleNamespace(office_code="B10", school_code="1234567", name="예시학교", kind="고등학교", address="서울")]
        neis.get_meals.return_value = [SimpleNamespace(date=self.start.isoformat(), meal_type="중식", menu="밥<br/>국", calories="500 kcal", nutrition="단백질 10g", origin="쌀")]
        with patch.dict("os.environ", {"NEIS_API_KEY": "test"}), patch("backend.app.NEISClient.from_environment", return_value=neis):
            path = "/api/v1/neis/schools"
            status, headers, body = dispatch_request("GET", path, "q=example", self.cache)
            self.assertEqual(status, 200)
            self.assert_json_response(path, status, headers, body)
            path = "/api/v1/meals"
            params = {"school": "B10:1234567", "from": self.start.isoformat(), "to": self.start.isoformat()}
            status, headers, body = dispatch_request("GET", path, urlencode(params), self.cache)
            self.assertEqual(status, 200)
            self.assert_json_response(path, status, headers, body)

        path = "/api/v1/timetable/history"
        store = Mock()
        store.list.return_value = {"changes": [{"observedAt": "2026-11-14T00:00:00Z", "grade": 2, "class": 3,
                                               "date": self.start.isoformat(), "period": 1, "type": "changed",
                                               "before": {"subject": "수학", "teacher": ""},
                                               "after": {"subject": "과학", "teacher": "김교사"}}], "nextCursor": None}
        with patch("backend.app._history_store", return_value=store):
            status, headers, body = dispatch_request("GET", path, urlencode({"school": "2:예시학교", "week": self.start.isoformat()}), self.cache)
        self.assertEqual(status, 200)
        self.assert_json_response(path, status, headers, body)

        path = "/api/v1/timetable/history.rss"
        store.list.return_value = {"changes": [], "nextCursor": None}
        with patch("backend.app._history_store", return_value=store):
            status, headers, body = dispatch_request("GET", path, urlencode({"school": "2:예시학교", "grade": 2, "class": 3}), self.cache)
        self.assertEqual(status, 200)
        self.assertTrue(headers["Content-Type"].startswith("application/rss+xml"))
        Draft202012Validator(self.response_schema(path, status, "application/rss+xml")).validate(body.decode("utf-8"))

    def test_calendar_modes_and_conditional_response_match_contract(self):
        path = "/api/v1/timetable.ics"
        week = self.start.isoformat()
        source = {"schoolId": "2:예시학교", "weekStart": week, "sourceUpdatedAt": None,
                  "fetchedAt": "2026-11-14T00:00:00Z", "stale": False,
                  "records": [dict(grade=2, date=week, period=1, subject="수학", teacher="김교사", isChanged=False, **{"class": 3})]}
        params = {"school": source["schoolId"], "grade": "2", "class": "3", "mode": "timed", "times": "1:0900-0950"}
        operation = self.spec["paths"][path]["get"]
        mode = next(p for p in operation["parameters"] if p["name"] == "mode")
        Draft202012Validator(mode["schema"]).validate(params["mode"])
        with patch("backend.app.fetch_timetable", return_value=source):
            status, headers, body = dispatch_request("GET", path, urlencode(params), self.cache)
            self.assertEqual(status, 200)
            self.assertTrue(headers["Content-Type"].startswith("text/calendar"))
            Draft202012Validator(self.response_schema(path, status, "text/calendar")).validate(body.decode("utf-8"))
            self.assertIn(b"BEGIN:VCALENDAR", body)
            self.assertIn(b"DTSTART:", body)
            self.assertIn("ETag", operation["responses"]["200"]["headers"])
            status, headers, body = dispatch_request("GET", path, urlencode(params), self.cache,
                                                     request_headers={"If-None-Match": headers["ETag"]})
        self.assertEqual((status, body), (304, b""))
        self.assertIn("ETag", operation["responses"]["304"]["headers"])
        self.assertIn("ETag", headers)


if __name__ == "__main__":
    unittest.main()
