import hmac
import json
import os
import re
import sqlite3
from urllib.parse import parse_qs


def record_pageview(method, request_body, client, headers, analytics_store, rate_allowed):
    if method != "POST":
        body = json.dumps({"error": "지원하지 않는 메서드입니다", "code": "method_not_allowed"}, ensure_ascii=False).encode("utf-8")
        headers["Content-Length"] = str(len(body))
        return 405, headers, body
    if len(request_body or b"") > 4096:
        body = json.dumps({"error": "요청 본문이 너무 큽니다", "code": "payload_too_large"}, ensure_ascii=False).encode("utf-8")
        headers["Content-Length"] = str(len(body))
        return 413, headers, body
    try:
        store = analytics_store()
    except (OSError, sqlite3.Error):
        store = None
    if store is None:
        body = json.dumps({"error": "분석 저장소가 설정되지 않았습니다", "code": "analytics_disabled"}, ensure_ascii=False).encode("utf-8")
        headers["Content-Length"] = str(len(body))
        return 503, headers, body
    if client:
        retry = rate_allowed(("analytics", client))
        if retry:
            body = json.dumps({"error": "요청이 너무 많습니다", "code": "rate_limited"}, ensure_ascii=False).encode("utf-8")
            headers["Retry-After"] = str(retry)
            headers["Content-Length"] = str(len(body))
            return 429, headers, body
    try:
        payload = json.loads(request_body or b"{}")
        if not isinstance(payload, dict):
            raise ValueError("analytics payload must be an object")
        store.record_pageview(payload.get("visitorId"), payload.get("sessionId"), payload.get("page"))
    except (ValueError, TypeError, AttributeError):
        body = json.dumps({"error": "분석 이벤트가 올바르지 않습니다", "code": "invalid_request"}, ensure_ascii=False).encode("utf-8")
        headers["Content-Length"] = str(len(body))
        return 400, headers, body
    except (OSError, sqlite3.Error):
        body = b'{"error":"Analytics temporarily unavailable","code":"analytics_unavailable"}'
        headers["Content-Length"] = str(len(body))
        return 503, headers, body
    body = b'{"accepted":true}'
    headers["Content-Length"] = str(len(body))
    return 202, headers, body


def analytics_summary(method, query_string, request_headers, headers, analytics_store, api_recorder):
    if method not in ("GET", "HEAD"):
        body = json.dumps({"error": "지원하지 않는 메서드입니다", "code": "method_not_allowed"}, ensure_ascii=False).encode("utf-8")
        headers["Content-Length"] = str(len(body))
        return 405, headers, body
    token = os.environ.get("OPENCIGAN_ANALYTICS_ADMIN_TOKEN", "")
    supplied = (request_headers or {}).get("Authorization", "")
    if not token or not hmac.compare_digest(supplied.encode("utf-8"), f"Bearer {token}".encode("utf-8")):
        headers["WWW-Authenticate"] = 'Bearer realm="OpenSigan analytics"'
        body = json.dumps({"error": "인증이 필요합니다", "code": "unauthorized"}, ensure_ascii=False).encode("utf-8")
        headers["Content-Length"] = str(len(body))
        return 401, headers, body
    try:
        store = analytics_store()
    except (OSError, sqlite3.Error):
        store = None
    if store is None:
        body = json.dumps({"error": "분석 저장소가 설정되지 않았습니다", "code": "analytics_disabled"}, ensure_ascii=False).encode("utf-8")
        headers["Content-Length"] = str(len(body))
        return 503, headers, body
    try:
        values = parse_qs(query_string, keep_blank_values=True).get("days", ["30"])
        if len(values) != 1 or not re.fullmatch(r"(?:[1-9]|[1-8][0-9]|90)", values[0]):
            raise ValueError("조회 기간은 1~90일이어야 합니다")
        days = int(values[0])
        result = store.summary(days)
        result["droppedApiEvents"] = api_recorder.dropped
    except (ValueError, TypeError):
        body = json.dumps({"error": "조회 기간은 1~90일이어야 합니다", "code": "invalid_request"}, ensure_ascii=False).encode("utf-8")
        headers["Content-Length"] = str(len(body))
        return 400, headers, body
    except (OSError, sqlite3.Error):
        body = b'{"error":"Analytics temporarily unavailable","code":"analytics_unavailable"}'
        headers["Content-Length"] = str(len(body))
        return 503, headers, body
    body = json.dumps(result, ensure_ascii=False).encode("utf-8")
    headers["Content-Length"] = str(len(body))
    return 200, headers, body
