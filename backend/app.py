import functools
import atexit
import ipaddress
import hashlib
import hmac
import json
import logging
import os
import re
import sqlite3
import socketserver
import threading
import time
import wsgiref.simple_server
from collections import OrderedDict, deque
from datetime import date, datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from backend.cache import Cache
from backend.analytics import ApiRecorder
from backend.access_logs import AccessLogRecorder, AccessLogStore, classify_origin
from backend.ical import render_timetable_ics
from backend.history_feed import render_history_feed
from backend.shutter import Shutter
from backend.neis import NEISClient, School
from backend.meal_routes import get_meals, search_meal_schools
from backend.timetable_routes import get_timetable, search_timetable_schools
from backend.timetable import fetch_timetable, search_schools, validate_timetable_week

cache = Cache()
shutter = Shutter.from_environment()
logger = logging.getLogger("opensigan")
_rate_lock = threading.Lock()
_rate_clients = OrderedDict()
_analytics_lock = threading.Lock()
_analytics_instance = None
_access_log_instance = None
_access_log_lock = threading.Lock()
_MAX_FORWARDED_HEADER_LEN = 1024
_MAX_FORWARDED_HOPS = 16


@functools.lru_cache(maxsize=64)
def _parse_trusted_cidr_item(item):
    try:
        return ipaddress.ip_network(item, strict=False)
    except ValueError:
        logger.warning("invalid trusted proxy CIDR: %r", item)
        return None


def parse_trusted_proxies(config):
    if not config:
        return ()
    if isinstance(config, (list, tuple, set)):
        items = [x.strip() if isinstance(x, str) else x for x in config]
    elif isinstance(config, str):
        items = [x.strip() for x in config.split(",") if x.strip()]
    else:
        return ()
    networks = []
    for item in items:
        if isinstance(item, (ipaddress.IPv4Network, ipaddress.IPv6Network)):
            networks.append(item)
        elif isinstance(item, str):
            net = _parse_trusted_cidr_item(item)
            if net is not None:
                networks.append(net)
    return tuple(networks)


def _clean_ip_str(raw):
    if not raw or not isinstance(raw, str):
        return None
    val = raw.strip()
    if val.startswith('"') and val.endswith('"'):
        val = val[1:-1]
    if not val:
        return None
    if val.startswith("["):
        match = re.fullmatch(r'\[([0-9a-fA-F:.]+)\](?::([0-9]{1,5}))?', val)
        if not match or (match[2] and not 1 <= int(match[2]) <= 65535):
            return None
        val = match[1]
    elif val.count(":") == 1:
        host, _, port = val.partition(":")
        if port.isdigit():
            if not 1 <= int(port) <= 65535:
                return None
            val = host
    if '%' in val:
        return None
    try:
        ip = ipaddress.ip_address(val)
        return getattr(ip, "ipv4_mapped", None) or ip
    except ValueError:
        return None


def resolve_client_ip(environ, trusted_proxies=None):
    remote_addr = environ.get("REMOTE_ADDR")
    if not remote_addr:
        return remote_addr

    if trusted_proxies is None:
        env_proxies = os.environ.get("OPENCIGAN_TRUSTED_PROXIES", "")
        trusted_networks = parse_trusted_proxies(env_proxies)
    else:
        trusted_networks = parse_trusted_proxies(trusted_proxies)

    if not trusted_networks:
        return remote_addr

    immediate_ip = _clean_ip_str(remote_addr)
    if immediate_ip is None:
        return remote_addr

    if not any(immediate_ip in net for net in trusted_networks):
        return str(immediate_ip)

    xff = environ.get("HTTP_X_FORWARDED_FOR")
    fwd = environ.get("HTTP_FORWARDED")
    if xff and fwd:
        return str(immediate_ip)

    hops = []
    if xff:
        if len(xff) > _MAX_FORWARDED_HEADER_LEN:
            return str(immediate_ip)
        hops = [h.strip() for h in xff.split(",")]
    elif fwd:
        if len(fwd) > _MAX_FORWARDED_HEADER_LEN:
            return str(immediate_ip)
        for hop in fwd.split(","):
            values = [part.strip().split('=', 1)[1].strip() for part in hop.split(';')
                      if re.match(r'(?i)^\s*for\s*=', part)]
            if len(values) != 1:
                return str(immediate_ip)
            hops.append(values[0])

    if not hops or len(hops) > _MAX_FORWARDED_HOPS:
        return str(immediate_ip)

    parsed_hops = [_clean_ip_str(hop) for hop in hops]
    if any(hop is None for hop in parsed_hops):
        return str(immediate_ip)

    client_ip = immediate_ip
    for hop_ip in reversed(parsed_hops):
        if any(hop_ip in net for net in trusted_networks):
            client_ip = hop_ip
            continue
        return str(hop_ip)

    return str(client_ip)


def _analytics_store():
    global _analytics_instance
    path = os.environ.get("OPENCIGAN_ANALYTICS_DB", "").strip()
    secret = os.environ.get("OPENCIGAN_ANALYTICS_SECRET", "")
    if not path or len(secret) < 32:
        return None
    with _analytics_lock:
        if _analytics_instance is None or _analytics_instance.path != path or _analytics_instance.secret != secret.encode("utf-8"):
            from backend.analytics import AnalyticsStore
            _analytics_instance = AnalyticsStore(path, secret)
        return _analytics_instance


def _access_log_store():
    global _access_log_instance
    path = os.environ.get('OPENCIGAN_ACCESS_LOG_DB', '').strip()
    if not path:
        return None
    days = int(os.environ.get('OPENCIGAN_ACCESS_LOG_RETENTION_DAYS', '7'))
    if not 1 <= days <= 90:
        raise ValueError('접속 로그 보관 기간은 1~90일이어야 합니다')
    with _access_log_lock:
        if _access_log_instance is None or _access_log_instance.path != path or _access_log_instance.retention_days != days:
            _access_log_instance = AccessLogStore(path, retention_days=days)
        return _access_log_instance


def _access_log_admin(method, query_string, request_headers, headers):
    if method not in ('GET', 'HEAD'):
        return 405, headers, b'{"code":"method_not_allowed"}'
    token = os.environ.get('OPENCIGAN_ACCESS_LOG_ADMIN_TOKEN', '')
    supplied = (request_headers or {}).get('Authorization', '')
    if not token or not hmac.compare_digest(supplied.encode(), ('Bearer ' + token).encode()):
        headers['WWW-Authenticate'] = 'Bearer realm="Opencigan access logs"'
        return 401, headers, b'{"code":"unauthorized"}'
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
        store = _access_log_store()
        if store is None:
            return 503, headers, b'{"code":"access_logs_disabled"}'
        if output == 'csv':
            headers['Content-Type'] = 'text/csv; charset=utf-8'
            headers['Content-Disposition'] = 'attachment; filename="opencigan-access.csv"'
            return 200, headers, ('\ufeff' + store.export_csv(filters, limit=5000)).encode()
        result = store.query(filters, cursor=cursor, limit=limit)
        result['dropped'] = _access_log_recorder.dropped
        return 200, headers, json.dumps(result, ensure_ascii=False).encode()
    except (ValueError, TypeError):
        return 400, headers, b'{"code":"invalid_request"}'
    except (OSError, sqlite3.Error):
        return 503, headers, b'{"code":"access_logs_unavailable"}'


def _rate_allowed(client):
    now = time.monotonic()
    with _rate_lock:
        while _rate_clients and next(iter(_rate_clients.values()))[-1] <= now - 60:
            _rate_clients.popitem(last=False)
        if client not in _rate_clients and len(_rate_clients) >= 4096:
            _rate_clients.popitem(last=False)
        requests = _rate_clients.setdefault(client, deque())
        while requests and requests[0] <= now - 60:
            requests.popleft()
        _rate_clients.move_to_end(client)
        if len(requests) >= 60:
            return max(1, int(61 - (now - requests[0])))
        requests.append(now)
        return 0


def _history_store():
    path = os.environ.get("OPENCIGAN_HISTORY_DB", "").strip()
    if not path:
        return None
    from backend.history import HistoryStore
    return HistoryStore(path)


def _webhook_store():
    path = os.environ.get("OPENCIGAN_HISTORY_DB", "").strip()
    if os.environ.get("OPENCIGAN_WEBHOOKS_ENABLED") != "1" or not path or not os.path.isfile(path):
        return None
    from backend.webhook_store import WebhookStore
    return WebhookStore(path)


def _webhook_api(method, path, body, request_headers, client, headers):
    from backend.webhook_store import SubscriptionLimitError

    def respond(status, payload):
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Length"] = str(len(encoded))
        return status, headers, encoded

    if client:
        retry = _rate_allowed(("webhooks", client))
        if retry:
            headers["Retry-After"] = str(retry)
            return respond(429, {"error": "요청이 너무 많습니다", "code": "rate_limited"})
    if len(body or b"") > 4096:
        return respond(413, {"error": "요청 본문이 너무 큽니다", "code": "payload_too_large"})
    try:
        store = _webhook_store()
        if store is None:
            return respond(503, {"error": "Webhook 기능이 활성화되지 않았습니다", "code": "webhooks_disabled"})
        if path == "/api/v1/webhooks":
            if method != "POST":
                return respond(405, {"error": "지원하지 않는 메서드입니다", "code": "method_not_allowed"})
            payload = json.loads(body or b"{}")
            if not isinstance(payload, dict) or set(payload) != {"school", "grade", "class", "destination"}:
                raise ValueError("invalid payload")
            result = store.create(payload["school"], payload["grade"], payload["class"], payload["destination"])
            return respond(200, result)
        match = re.fullmatch(r"/api/v1/webhooks/([A-Za-z0-9_-]{24})(/deliveries|/test)?", path)
        if not match:
            return respond(404, {"error": "요청한 경로가 없습니다", "code": "not_found"})
        if method not in ("GET", "HEAD", "DELETE", "POST", "PUT"):
            return respond(405, {"error": "지원하지 않는 메서드입니다", "code": "method_not_allowed"})
        authorization = (request_headers or {}).get("Authorization", "")
        token = authorization[7:] if authorization.startswith("Bearer ") else ""
        identifier = match.group(1)
        if match.group(2) == "/test":
            if method != "POST":
                return respond(405, {"error": "지원하지 않는 메서드입니다", "code": "method_not_allowed"})
            event = store.enqueue_test(identifier, token)
            if event is False:
                headers["Retry-After"] = "60"
                return respond(429, {"error": "잠시 후 다시 시도해 주세요", "code": "rate_limited"})
            result = {"eventId": event} if event is not None else None
        elif match.group(2) == "/deliveries":
            if method not in ("GET", "HEAD"):
                return respond(405, {"error": "지원하지 않는 메서드입니다", "code": "method_not_allowed"})
            deliveries = store.deliveries(identifier, token)
            result = {"deliveries": deliveries} if deliveries is not None else None
        elif method == "POST":
            return respond(405, {"error": "지원하지 않는 메서드입니다", "code": "method_not_allowed"})
        elif method == "PUT":
            payload = json.loads(body or b"{}")
            if not isinstance(payload, dict) or set(payload) != {"filters"}:
                raise ValueError("invalid payload")
            result = {"updated": True} if store.update_filters(identifier, token, payload["filters"]) else None
        elif method == "DELETE":
            result = {"deleted": True} if store.delete(identifier, token) else None
        else:
            result = store.get(identifier, token)
        if result is None:
            return respond(401, {"error": "인증이 필요합니다", "code": "unauthorized"})
        return respond(200, result)
    except SubscriptionLimitError:
        return respond(503, {"error": "구독 한도에 도달했습니다", "code": "subscription_limit"})
    except (ValueError, TypeError, UnicodeDecodeError, RecursionError):
        return respond(400, {"error": "요청 값이 올바르지 않습니다", "code": "invalid_request"})
    except (OSError, sqlite3.Error):
        return respond(503, {"error": "Webhook 저장소를 사용할 수 없습니다", "code": "webhooks_unavailable"})


def _query_param(params, key, limit):
    values = params.get(key, [])
    if len(values) != 1 or not values[0].strip() or len(values[0]) > limit:
        raise ValueError(f"{key} 값이 올바르지 않습니다")
    return values[0].strip()


def _timetable_filters(query, require_class=False):
    grade_filter = None
    class_filter = None
    teacher_filter = None
    if require_class or "grade" in query:
        raw_grade = _query_param(query, "grade", 1)
        if not re.fullmatch(r"[1-6]", raw_grade):
            raise ValueError("grade는 1부터 6까지의 정수여야 합니다")
        grade_filter = int(raw_grade)
    if require_class or "class" in query:
        raw_class = _query_param(query, "class", 2)
        if not re.fullmatch(r"[1-9][0-9]?", raw_class):
            raise ValueError("class는 1부터 99까지의 정수여야 합니다")
        class_filter = int(raw_class)
    if "teacher" in query:
        teacher_filter = _query_param(query, "teacher", 50).casefold()
    return grade_filter, class_filter, teacher_filter


def _cached_timetable(school, week, current_cache):
    def fetch_and_record():
        started_at = datetime.now(timezone.utc).isoformat()
        data = fetch_timetable(school, week)
        try:
            store = _history_store()
            if store is not None and not data.get("stale", False):
                store.observe(school, week, data["records"], observed_at=data["fetchedAt"], started_at=started_at)
        except Exception:
            logger.exception("history recording failed")
        return data

    return current_cache.get(("timetable", school, week), fetch_and_record, with_status=True)


def _read_request_body(stream, content_length):
    try:
        length = int(content_length or "0")
    except (TypeError, ValueError):
        return b""
    if length < 0:
        return b""
    if length > 4096:
        return b" " * 4097
    return stream.read(length) if stream is not None else b""


def _dispatch_request(method, path, query_string, cache_instance=None, client=None, request_origin=None, request_body=None, request_headers=None, shutter_instance=None):
    current_cache = cache if cache_instance is None else cache_instance
    origin = os.environ.get("ALLOWED_ORIGIN", "")

    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "Cache-Control": "no-store",
    }
    if origin:
        headers["Vary"] = "Origin"
    if origin and (request_origin is None or request_origin in [item.strip() for item in origin.split(",")]):
        headers["Access-Control-Allow-Origin"] = request_origin or origin.split(",")[0].strip()
        headers["Access-Control-Expose-Headers"] = "Retry-After, ETag" if path in ("/api/v1/timetable.ics", "/api/v1/timetable/history.rss") else "Retry-After"

    if method == "OPTIONS":
        headers["Access-Control-Allow-Methods"] = "GET, HEAD, POST, PUT, DELETE, OPTIONS" if path.startswith("/api/v1/webhooks") else "GET, HEAD, POST, OPTIONS"
        headers["Access-Control-Allow-Headers"] = (
            "Content-Type, Authorization, If-None-Match" if path in ("/api/v1/timetable.ics", "/api/v1/timetable/history.rss")
            else "Content-Type, Authorization"
        )
        headers["Content-Length"] = "0"
        return 204, headers, b""

    if path == '/api/v1/admin/access-logs':
        status, response_headers, body = _access_log_admin(method, query_string, request_headers, headers)
        response_headers['Content-Length'] = str(len(body))
        return status, response_headers, body

    if path not in ("/api/v1/status", "/api/v1/admin/analytics"):
        allowed, retry_after = (shutter if shutter_instance is None else shutter_instance).check()
        if not allowed:
            body = json.dumps({"error": "요청이 집중되어 일시적으로 중단되었습니다. 잠시 후 다시 시도해 주세요.", "code": "service_overloaded", "retry_after": retry_after}, ensure_ascii=False).encode("utf-8")
            headers["Retry-After"] = str(retry_after)
            headers["Content-Length"] = str(len(body))
            return 503, headers, body

    if path == "/api/v1/webhooks" or path.startswith("/api/v1/webhooks/"):
        return _webhook_api(method, path, request_body, request_headers, client, headers)

    if path == "/api/v1/analytics/pageview":
        if method != "POST":
            body = json.dumps({"error": "지원하지 않는 메서드입니다", "code": "method_not_allowed"}, ensure_ascii=False).encode("utf-8")
            headers["Content-Length"] = str(len(body))
            return 405, headers, body
        if len(request_body or b"") > 4096:
            body = json.dumps({"error": "요청 본문이 너무 큽니다", "code": "payload_too_large"}, ensure_ascii=False).encode("utf-8")
            headers["Content-Length"] = str(len(body))
            return 413, headers, body
        try:
            store = _analytics_store()
        except (OSError, sqlite3.Error):
            store = None
        if store is None:
            body = json.dumps({"error": "분석 저장소가 설정되지 않았습니다", "code": "analytics_disabled"}, ensure_ascii=False).encode("utf-8")
            headers["Content-Length"] = str(len(body))
            return 503, headers, body
        if client:
            retry = _rate_allowed(("analytics", client))
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

    if path == "/api/v1/admin/analytics":
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
            store = _analytics_store()
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
            result["droppedApiEvents"] = _api_recorder.dropped
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

    if method not in ("GET", "HEAD"):
        body = json.dumps({"error": "지원하지 않는 메서드입니다", "code": "method_not_allowed"}, ensure_ascii=False).encode("utf-8")
        headers["Content-Length"] = str(len(body))
        return 405, headers, body

    if client and path != "/api/v1/status":
        retry = _rate_allowed(client)
        if retry:
            body = json.dumps({"error": "요청이 너무 많습니다. 잠시 후 다시 시도해 주세요.", "code": "rate_limited"}, ensure_ascii=False).encode("utf-8")
            headers["Retry-After"] = str(retry)
            headers["Content-Length"] = str(len(body))
            return 429, headers, body
    query = parse_qs(query_string, keep_blank_values=path == "/api/v1/timetable/history.rss")
    try:
        if path == "/api/v1/status":
            result = {"status": "ok", "scope": "process liveness"}
        elif path == "/api/v1/schools":
            result = search_timetable_schools(query, current_cache, _query_param, search_schools)
        elif path == "/api/v1/timetable":
            result = get_timetable(query, current_cache, _query_param, validate_timetable_week, _timetable_filters, _cached_timetable)
        elif path == "/api/v1/timetable.ics":
            school = _query_param(query, "school", 100)
            if not re.fullmatch(r"[0-9]+:[^:]{1,50}", school):
                raise ValueError("학교 식별자가 올바르지 않습니다")
            grade_filter, class_filter, teacher_filter = _timetable_filters(query, require_class=True)
            weeks = _query_param(query, "weeks", 1) if "weeks" in query else "1"
            if weeks not in ("1", "2"):
                raise ValueError("weeks는 1 또는 2여야 합니다")
            mode = _query_param(query, "mode", 10) if "mode" in query else "periods"
            if mode not in ("periods", "summary", "timed"):
                raise ValueError("mode는 periods, summary 또는 timed여야 합니다")
            lesson_times = {}
            if "times" in query:
                if mode != "timed":
                    raise ValueError("교시 시각은 timed 모드에서만 사용할 수 있습니다")
                raw_times = _query_param(query, "times", 400)
                for item in raw_times.split(","):
                    match = re.fullmatch(r"([1-9]|1[0-9]|20):([0-2][0-9][0-5][0-9])-([0-2][0-9][0-5][0-9])", item)
                    if not match:
                        raise ValueError("교시 시각 형식은 1:0900-0950입니다")
                    period = int(match[1])
                    start = match[2][:2] + ":" + match[2][2:]
                    end = match[3][:2] + ":" + match[3][2:]
                    if period in lesson_times or start >= end or end > "23:59":
                        raise ValueError("교시 시각의 중복·범위·순서를 확인하세요")
                    lesson_times[period] = {"start": start, "end": end}
                ordered = [value for _, value in sorted(lesson_times.items())]
                if any(value["start"] < ordered[index - 1]["end"] for index, value in enumerate(ordered) if index):
                    raise ValueError("교시 시각이 겹칩니다")
            now = datetime.now(timezone(timedelta(hours=9))).date()
            monday = now - timedelta(days=now.weekday())
            timetables = []
            for offset in range(int(weeks)):
                week = (monday + timedelta(days=offset * 7)).isoformat()
                timetable, _ = _cached_timetable(school, week, current_cache)
                if teacher_filter is not None:
                    timetable = {**timetable, "records": [r for r in timetable["records"]
                                 if teacher_filter in (r.get("teacher") or "").casefold()]}
                timetables.append(timetable)
            body = render_timetable_ics(school, grade_filter, class_filter, timetables, mode=mode, lesson_times=lesson_times)
            etag = '"' + hashlib.sha256(body).hexdigest() + '"'
            headers["ETag"] = etag
            headers["Cache-Control"] = "private, max-age=0, must-revalidate"
            headers["Content-Type"] = "text/calendar; charset=utf-8"
            headers["Content-Disposition"] = 'inline; filename="opencigan.ics"'
            validators = (request_headers or {}).get("If-None-Match", "").strip()
            if validators == "*" or etag in (tag.strip().removeprefix("W/") for tag in validators.split(",")):
                return 304, headers, b""
            headers["Content-Length"] = str(len(body))
            return 200, headers, body
        elif path in ("/api/v1/timetable/history", "/api/v1/timetable/history.rss"):
            school = _query_param(query, "school", 100)
            if not re.fullmatch(r"[0-9]+:[^:]{1,50}", school):
                raise ValueError("학교 식별자가 올바르지 않습니다")
            if path.endswith(".rss") and "week" not in query:
                now = datetime.now(timezone(timedelta(hours=9))).date()
                week = (now - timedelta(days=now.weekday())).isoformat()
            else:
                week = _query_param(query, "week", 10)
            parsed_week = date.fromisoformat(week)
            if parsed_week.isoformat() != week or parsed_week.weekday() != 0:
                raise ValueError("주 시작일이 올바르지 않습니다")
            cursor = _query_param(query, "cursor", 100) if "cursor" in query else None
            store = _history_store()
            if store is None:
                body = json.dumps({"error": "변경 이력 저장이 활성화되지 않았습니다", "code": "history_disabled"}, ensure_ascii=False).encode("utf-8")
                headers["Content-Length"] = str(len(body))
                return 503, headers, body
            if path.endswith(".rss"):
                grade_filter, class_filter, _ = _timetable_filters({key: value for key, value in query.items() if key != "teacher"}, require_class=True)
                if cursor is not None:
                    raise ValueError("피드에는 커서를 사용할 수 없습니다")
                filters = {key: _query_param(query, key, 50) for key in ("subject", "teacher") if key in query}
                if "weekday" in query:
                    filters["weekday"] = _query_param(query, "weekday", 1)
                    if filters["weekday"] not in ("1", "2", "3", "4", "5"):
                        raise ValueError("weekday는 1(월)부터 5(금)까지여야 합니다")
                if "period" in query:
                    raw_period = _query_param(query, "period", 2)
                    if not re.fullmatch(r"(?:[1-9]|1[0-9]|20)", raw_period):
                        raise ValueError("period는 1부터 20까지여야 합니다")
                    filters["period"] = int(raw_period)
                if "type" in query:
                    filters["type"] = _query_param(query, "type", 7)
                    if filters["type"] not in ("added", "deleted", "changed"):
                        raise ValueError("type이 올바르지 않습니다")
                group = _query_param(query, "group", 7) if "group" in query else "changes"
                if group not in ("changes", "daily"):
                    raise ValueError("group은 changes 또는 daily여야 합니다")
                changes = store.list(school, week, grade=grade_filter, classroom=class_filter, include_ids=True, filters=filters)["changes"]
                body = render_history_feed(school, grade_filter, class_filter, changes, group=group)
                etag = '"' + hashlib.sha256(body).hexdigest() + '"'
                headers.update({"Content-Type": "application/rss+xml; charset=utf-8", "ETag": etag,
                                "Cache-Control": "private, max-age=0, must-revalidate"})
                validators = (request_headers or {}).get("If-None-Match", "").strip()
                if validators == "*" or etag in (tag.strip().removeprefix("W/") for tag in validators.split(",")):
                    return 304, headers, b""
                headers["Content-Length"] = str(len(body))
                return 200, headers, body
            result = store.list(school, week, cursor=cursor)
        elif path == "/api/v1/neis/schools":
            result = search_meal_schools(query, current_cache, _query_param, NEISClient)
        elif path == "/api/v1/meals":
            result = get_meals(query, current_cache, _query_param, NEISClient, School)
        else:
            body = json.dumps({"error": "요청한 경로가 없습니다", "code": "not_found"}, ensure_ascii=False).encode("utf-8")
            headers["Content-Length"] = str(len(body))
            return 404, headers, body

        body = json.dumps(result, ensure_ascii=False).encode("utf-8")
        headers["Content-Length"] = str(len(body))
        return 200, headers, body
    except ValueError as exc:
        body = json.dumps({"error": str(exc), "code": "invalid_request"}, ensure_ascii=False).encode("utf-8")
        headers["Content-Length"] = str(len(body))
        return 400, headers, body
    except Exception:
        logger.exception("upstream request failed")
        body = json.dumps(
            {"error": "데이터를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.", "code": "upstream_unavailable"},
            ensure_ascii=False,
        ).encode("utf-8")
        headers["Content-Length"] = str(len(body))
        return 503, headers, body


_api_recorder = ApiRecorder(_analytics_store)
_access_log_recorder = AccessLogRecorder(_access_log_store)
atexit.register(_access_log_recorder.close)


def dispatch_request(method, path, query_string, cache_instance=None, client=None, request_origin=None, request_body=None, request_headers=None, shutter_instance=None):
    received_at = datetime.now(timezone(timedelta(hours=9)))
    started = time.perf_counter()
    response = _dispatch_request(method, path, query_string, cache_instance, client, request_origin, request_body, request_headers, shutter_instance)
    if method in ("GET", "HEAD") and path in ("/api/v1/schools", "/api/v1/neis/schools", "/api/v1/timetable", "/api/v1/timetable.ics", "/api/v1/timetable/history", "/api/v1/timetable/history.rss", "/api/v1/meals") and os.environ.get("OPENCIGAN_ANALYTICS_DB"):
        metadata = {}
        if (path == "/api/v1/timetable" or response[0] >= 500) and response[1].get("Content-Type", "").startswith("application/json"):
            try:
                payload = json.loads(response[2])
                if isinstance(payload, dict):
                    metadata = payload
            except (ValueError, TypeError):
                pass
        _api_recorder.submit(path, method, response[0], (time.perf_counter() - started) * 1000,
                             metadata.get("cacheStatus"), metadata.get("code") if response[0] >= 500 else None)
    if os.environ.get('OPENCIGAN_ACCESS_LOG_DB') and not path.startswith('/api/v1/admin/'):
        origin_class, referrer_origin = classify_origin(request_origin, (request_headers or {}).get('Referer'), os.environ.get('ALLOWED_ORIGIN', ''))
        fields = {}
        try:
            query = parse_qs(query_string, max_num_fields=30)
            for key in ('school', 'grade', 'class', 'week', 'from', 'to') if path in ('/api/v1/timetable', '/api/v1/timetable.ics', '/api/v1/timetable/history', '/api/v1/timetable/history.rss', '/api/v1/meals') else ():
                items = query.get(key, [])
                if len(items) == 1 and len(items[0]) <= 100:
                    value = items[0]
                    if key == 'school':
                        if re.fullmatch(r'[A-Z][0-9]{2}:[0-9]{7}' if path == '/api/v1/meals' else r'[0-9]+:[^:\x00-\x1f\x7f]{1,50}', value):
                            fields[key] = value
                    elif key in ('grade', 'class'):
                        if re.fullmatch(r'[1-6]' if key == 'grade' else r'[1-9][0-9]?', value):
                            fields[key] = value
                    else:
                        try:
                            if date.fromisoformat(value).isoformat() == value:
                                fields[key] = value
                        except ValueError:
                            pass
        except ValueError:
            pass
        cache_status = None
        if response[0] == 200 and response[1].get('Content-Type', '').startswith('application/json'):
            cache_status = json.loads(response[2]).get('cacheStatus')
        _access_log_recorder.submit({
            'client_ip': client or '', 'method': method,
            'route': path if path in ('/api/v1/status', '/api/v1/schools', '/api/v1/neis/schools', '/api/v1/timetable', '/api/v1/timetable.ics', '/api/v1/timetable/history', '/api/v1/timetable/history.rss', '/api/v1/meals', '/api/v1/analytics/pageview') else '/unknown',
            'school_id': fields.get('school'), 'grade': fields.get('grade'), 'class_nm': fields.get('class'),
            'week': fields.get('week'), 'dates': fields.get('from', '') + ('~' + fields['to'] if fields.get('to') else ''),
            'datatype': 'meals' if path == '/api/v1/meals' else 'timetable' if path.startswith('/api/v1/timetable') else 'other',
            'status': response[0], 'duration_ms': (time.perf_counter() - started) * 1000,
            'cache_status': cache_status, 'referrer_origin': referrer_origin, 'origin_class': origin_class,
        }, received_at=received_at)
    return response


class Handler(BaseHTTPRequestHandler):
    def _unsupported(self):
        parts = urlsplit(self.path)
        request_body = _read_request_body(self.rfile, self.headers.get("Content-Length")) if (self.command == "POST" and parts.path == "/api/v1/analytics/pageview") or (self.command in ("POST", "PUT") and parts.path.startswith("/api/v1/webhooks")) else None
        status_code, headers, body = dispatch_request(self.command, parts.path, parts.query, cache, self.client_address[0], self.headers.get("Origin"), request_body, {"Authorization": self.headers.get("Authorization", ""), "Referer": self.headers.get("Referer", "")})
        self.send_response(status_code)
        for key, val in headers.items():
            self.send_header(key, val)
        self.end_headers()
        self.wfile.write(body)

    do_POST = do_PUT = do_PATCH = do_DELETE = _unsupported

    def do_OPTIONS(self):
        parts = urlsplit(self.path)
        status_code, headers, body = dispatch_request("OPTIONS", parts.path, parts.query, cache, self.client_address[0], self.headers.get("Origin"), request_headers={"Referer": self.headers.get("Referer", "")})
        self.send_response(status_code)
        for key, val in headers.items():
            self.send_header(key, val)
        self.end_headers()

    def do_HEAD(self):
        parts = urlsplit(self.path)
        status_code, headers, body = dispatch_request("HEAD", parts.path, parts.query, cache, self.client_address[0], self.headers.get("Origin"), request_headers={"Authorization": self.headers.get("Authorization", ""), "If-None-Match": self.headers.get("If-None-Match", ""), "Referer": self.headers.get("Referer", "")})
        self.send_response(status_code)
        for key, val in headers.items():
            self.send_header(key, val)
        self.end_headers()

    def do_GET(self):
        parts = urlsplit(self.path)
        status_code, headers, body = dispatch_request("GET", parts.path, parts.query, cache, self.client_address[0], self.headers.get("Origin"), request_headers={"Authorization": self.headers.get("Authorization", ""), "If-None-Match": self.headers.get("If-None-Match", ""), "Referer": self.headers.get("Referer", "")})
        self.send_response(status_code)
        for key, val in headers.items():
            self.send_header(key, val)
        self.end_headers()
        if body:
            self.wfile.write(body)

    @staticmethod
    def query(params, key, limit):
        return _query_param(params, key, limit)

    def respond(self, status, result, origin):
        data = json.dumps(result, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


_STATUS_PHRASES = {
    200: "200 OK",
    202: "202 Accepted",
    204: "204 No Content",
    304: "304 Not Modified",
    400: "400 Bad Request",
    401: "401 Unauthorized",
    404: "404 Not Found",
    405: "405 Method Not Allowed",
    429: "429 Too Many Requests",
    413: "413 Payload Too Large",
    500: "500 Internal Server Error",
    503: "503 Service Unavailable",
}


def make_app(cache_instance=None, trusted_proxies=None):
    """Create a PEP 3333 compliant WSGI application."""

    def wsgi_application(environ, start_response):
        method = environ.get("REQUEST_METHOD", "GET").upper()
        path = environ.get("PATH_INFO", "") or "/"
        query_string = environ.get("QUERY_STRING", "")
        client = resolve_client_ip(environ, trusted_proxies=trusted_proxies)

        status_code, headers, body = dispatch_request(
            method=method,
            path=path,
            query_string=query_string,
            cache_instance=cache_instance,
            client=client,
            request_origin=environ.get("HTTP_ORIGIN"),
            request_body=_read_request_body(environ.get("wsgi.input"), environ.get("CONTENT_LENGTH")) if (method == "POST" and path == "/api/v1/analytics/pageview") or (method in ("POST", "PUT") and path.startswith("/api/v1/webhooks")) else None,
            request_headers={"Authorization": environ.get("HTTP_AUTHORIZATION", ""), "If-None-Match": environ.get("HTTP_IF_NONE_MATCH", ""), "Referer": environ.get("HTTP_REFERER", "")},
        )

        status_line = _STATUS_PHRASES.get(status_code, f"{status_code} Unknown")
        start_response(status_line, list(headers.items()))
        if method == "HEAD":
            return [b""]
        return [body]

    return wsgi_application


app = make_app()
application = app


class ThreadingWSGIServer(socketserver.ThreadingMixIn, wsgiref.simple_server.WSGIServer):
    daemon_threads = True
    allow_reuse_address = True


def serve(host=None, port=None, wsgi_app=None):
    host = host or os.environ.get("HOST", "127.0.0.1")
    port = int(port or os.environ.get("PORT", "8000"))
    target_app = wsgi_app or app

    try:
        import waitress

        threads = int(os.environ.get("THREADS", "8"))
        logger.info("Starting Waitress WSGI server on %s:%s (threads=%d)", host, port, threads)
        waitress.serve(target_app, host=host, port=port, threads=threads)
    except ImportError:
        logger.info("Waitress not installed. Serving with ThreadingWSGIServer on %s:%s", host, port)
        server = wsgiref.simple_server.make_server(
            host, port, target_app, server_class=ThreadingWSGIServer
        )
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    serve()
