import hmac
import json
import os
import sqlite3
from datetime import date
from urllib.parse import parse_qs

from backend.http_core import json_response


def access_log_admin(method, query_string, request_headers, headers, access_log_store, recorder):
    if method not in ('GET', 'HEAD'):
        return json_response(405, headers, {"error": "지원하지 않는 메서드입니다", "code": "method_not_allowed"})
    token = os.environ.get('OPENCIGAN_ACCESS_LOG_ADMIN_TOKEN', '')
    supplied = (request_headers or {}).get('Authorization', '')
    if not token or not hmac.compare_digest(supplied.encode(), ('Bearer ' + token).encode()):
        headers['WWW-Authenticate'] = 'Bearer realm="Opencigan access logs"'
        return json_response(401, headers, {"error": "인증이 필요합니다", "code": "unauthorized"})
    try:
        values = parse_qs(query_string, keep_blank_values=True, max_num_fields=20)
        allowed = {'client_ip', 'school_id', 'grade', 'class', 'start_day', 'end_day', 'route', 'status', 'origin_class', 'cache_status', 'cursor', 'limit', 'format'}
        if set(values) - allowed or any(len(items) != 1 or len(items[0]) > 255 for items in values.values()):
            raise ValueError('조회 조건이 올바르지 않습니다')
        filters = {key: item[0] for key, item in values.items() if key not in ('cursor', 'limit', 'format') and item[0]}
        for key in ('start_day', 'end_day'):
            if key in filters and date.fromisoformat(filters[key]).isoformat() != filters[key]:
                raise ValueError('날짜를 확인하세요')
        if filters.get('start_day', '') > filters.get('end_day', '9999-12-31'):
            raise ValueError('날짜 범위를 확인하세요')
        for key, low, high in [('grade', 1, 6), ('class', 1, 99), ('status', 100, 599)]:
            if key in filters and (not filters[key].isdigit() or not low <= int(filters[key]) <= high):
                raise ValueError('숫자 조건을 확인하세요')
        cursor = values.get('cursor', [None])[0]
        if cursor is not None and (not cursor.isdigit() or int(cursor) <= 0):
            raise ValueError('커서를 확인하세요')
        if 'origin_class' in filters and filters['origin_class'] not in ('frontend', 'external', 'unknown'):
            raise ValueError('출처 조건을 확인하세요')
        limit = int(values.get('limit', ['50'])[0])
        if not 1 <= limit <= 100:
            raise ValueError('조회 건수는 1~100입니다')
        output = values.get('format', ['json'])[0]
        if output not in ('json', 'csv'):
            raise ValueError('형식을 확인하세요')
        store = access_log_store()
        if store is None:
            return json_response(503, headers, {"error": "접속 로그가 비활성화되어 있습니다", "code": "access_logs_disabled"})
        if output == 'csv':
            headers['Content-Type'] = 'text/csv; charset=utf-8'
            headers['Content-Disposition'] = 'attachment; filename="opencigan-access.csv"'
            return 200, headers, ('\ufeff' + store.export_csv(filters, limit=5000)).encode()
        result = store.query(filters, cursor=cursor, limit=limit)
        result['dropped'] = recorder.dropped
        return 200, headers, json.dumps(result, ensure_ascii=False).encode()
    except (ValueError, TypeError):
        return json_response(400, headers, {"error": "조회 조건이 올바르지 않습니다", "code": "invalid_request"})
    except (OSError, sqlite3.Error):
        return json_response(503, headers, {"error": "접속 로그를 불러오지 못했습니다", "code": "access_logs_unavailable"})


def access_anomaly_review(method, query_string, request_headers, headers, access_log_store):
    def bad_request(message):
        return json_response(400, headers, {"error": message, "code": "invalid_request"})

    def unavailable():
        return json_response(503, headers, {"error": "접속 로그가 비활성화되어 있습니다", "code": "access_logs_disabled"})

    if method not in ("GET", "HEAD"):
        return json_response(405, headers, {"error": "지원하지 않는 메서드입니다", "code": "method_not_allowed"})

    token = os.environ.get("OPENCIGAN_ACCESS_LOG_ADMIN_TOKEN", "")
    supplied = (request_headers or {}).get("Authorization", "")
    if not token or not hmac.compare_digest(supplied.encode(), ("Bearer " + token).encode()):
        headers["WWW-Authenticate"] = 'Bearer realm="Opencigan access log anomalies"'
        return json_response(401, headers, {"error": "인증이 필요합니다", "code": "unauthorized"})

    try:
        values = parse_qs(query_string, keep_blank_values=True, max_num_fields=10)
        allowed = {"window_hours", "max_requests_per_ip", "max_error_ratio", "max_distinct_schools", "min_requests"}
        if set(values) - allowed or any(len(items) != 1 or len(items[0]) > 32 for items in values.values()):
            raise ValueError("invalid query")
        window_hours = int(values.get("window_hours", ["24"])[0])
        if not 1 <= window_hours <= 720:
            raise ValueError("invalid window")
        max_requests_per_ip = int(values.get("max_requests_per_ip", ["1000"])[0])
        if not 1 <= max_requests_per_ip <= 100000:
            raise ValueError("invalid volume threshold")
        max_error_ratio = float(values.get("max_error_ratio", ["0.5"])[0])
        if not 0 < max_error_ratio <= 1:
            raise ValueError("invalid error ratio")
        max_distinct_schools = int(values.get("max_distinct_schools", ["50"])[0])
        if not 1 <= max_distinct_schools <= 100000:
            raise ValueError("invalid school threshold")
        min_requests = int(values.get("min_requests", ["20"])[0])
        if not 0 <= min_requests <= 1000000:
            raise ValueError("invalid minimum")
        store = access_log_store()
        if store is None:
            return unavailable()
        findings = store.review_anomalies(
            window_hours=window_hours, max_requests_per_ip=max_requests_per_ip,
            max_error_ratio=max_error_ratio, max_distinct_schools=max_distinct_schools,
            min_requests=min_requests,
        )
    except ValueError:
        return bad_request("숫자 형식이나 범위가 올바르지 않습니다")
    except (OSError, sqlite3.Error):
        return json_response(503, headers, {"error": "접속 로그를 불러오지 못했습니다", "code": "access_logs_unavailable"})
    return json_response(200, headers, {"findings": findings, "window_hours": window_hours, "thresholds": {"max_requests_per_ip": max_requests_per_ip, "max_error_ratio": max_error_ratio, "max_distinct_schools": max_distinct_schools, "min_requests": min_requests}})
