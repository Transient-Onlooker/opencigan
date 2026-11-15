import hmac
import json
import os
import re
import sqlite3
from urllib.parse import parse_qs

from backend.http_core import json_response

def record_pageview(method, request_body, client, headers, analytics_store, rate_allowed):
    if method != "POST":
        return json_response(405, headers, {"error": "지원하지 않는 메서드입니다", "code": "method_not_allowed"})
    if len(request_body or b"") > 4096:
        return json_response(413, headers, {"error": "요청 본문이 너무 큽니다", "code": "payload_too_large"})
    try:
        store = analytics_store()
    except (OSError, sqlite3.Error):
        store = None
    if store is None:
        return json_response(503, headers, {"error": "분석 저장소가 설정되지 않았습니다", "code": "analytics_disabled"})
    if client:
        retry = rate_allowed(("analytics", client))
        if retry:
            headers["Retry-After"] = str(retry)
            return json_response(429, headers, {"error": "요청이 너무 많습니다", "code": "rate_limited"})
    try:
        payload = json.loads(request_body or b"{}")
        if not isinstance(payload, dict):
            raise ValueError("analytics payload must be an object")
        store.record_pageview(payload.get("visitorId"), payload.get("sessionId"), payload.get("page"))
    except (ValueError, TypeError, AttributeError):
        return json_response(400, headers, {"error": "분석 이벤트가 올바르지 않습니다", "code": "invalid_request"})
    except (OSError, sqlite3.Error):
        body = b'{"error":"Analytics temporarily unavailable","code":"analytics_unavailable"}'
        headers["Content-Length"] = str(len(body))
        return 503, headers, body
    body = b'{"accepted":true}'
    headers["Content-Length"] = str(len(body))
    return 202, headers, body


def analytics_summary(method, query_string, request_headers, headers, analytics_store, api_recorder):
    if method not in ("GET", "HEAD"):
        return json_response(405, headers, {"error": "지원하지 않는 메서드입니다", "code": "method_not_allowed"})
    token = os.environ.get("OPENCIGAN_ANALYTICS_ADMIN_TOKEN", "")
    supplied = (request_headers or {}).get("Authorization", "")
    if not token or not hmac.compare_digest(supplied.encode("utf-8"), f"Bearer {token}".encode("utf-8")):
        headers["WWW-Authenticate"] = 'Bearer realm="OpenSigan analytics"'
        return json_response(401, headers, {"error": "인증이 필요합니다", "code": "unauthorized"})
    try:
        store = analytics_store()
    except (OSError, sqlite3.Error):
        store = None
    if store is None:
        return json_response(503, headers, {"error": "분석 저장소가 설정되지 않았습니다", "code": "analytics_disabled"})
    try:
        values = parse_qs(query_string, keep_blank_values=True).get("days", ["30"])
        if len(values) != 1 or not re.fullmatch(r"(?:[1-9]|[1-8][0-9]|90)", values[0]):
            raise ValueError("조회 기간은 1~90일이어야 합니다")
        days = int(values[0])
        result = store.summary(days)
        result["droppedApiEvents"] = api_recorder.dropped
    except (ValueError, TypeError):
        return json_response(400, headers, {"error": "조회 기간은 1~90일이어야 합니다", "code": "invalid_request"})
    except (OSError, sqlite3.Error):
        body = b'{"error":"Analytics temporarily unavailable","code":"analytics_unavailable"}'
        headers["Content-Length"] = str(len(body))
        return 503, headers, body
    return json_response(200, headers, result)
