import functools
import atexit
import ipaddress
import json
import logging
import os
import re
import socketserver
import threading
import time
import wsgiref.simple_server
from collections import OrderedDict, deque
from datetime import date, datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from backend.cache import Cache, CacheBackoffError
from backend.http_core import json_response, make_response_headers, preflight_response, query_param as _query_param, timetable_filters
from backend.analytics import ApiRecorder
from backend.access_logs import AccessLogRecorder, AccessLogStore, classify_origin
from backend.signed_client_ip import verify_signed_client_ip
from backend.ical import render_timetable_ics
from backend.history_feed import render_history_feed
from backend.shutter import Shutter
from backend.neis import NEISClient, School
from backend.meal_routes import get_meals, search_meal_schools
from backend.timetable_routes import get_timetable, search_timetable_schools
from backend.webhook_routes import webhook_api
from backend.suggestion_routes import suggestion_api
from backend.calendar_routes import timetable_calendar
from backend.history_routes import timetable_history
from backend.analytics_routes import record_pageview, analytics_summary
from backend.admin_routes import access_log_admin
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
_suggestion_lock = threading.Lock()
_suggestion_instance = None
_MAX_FORWARDED_HEADER_LEN = 1024
_MAX_FORWARDED_HOPS = 16


def _log_request_failure(path, exc):
    route = path if path in ("/api/v1/schools", "/api/v1/timetable", "/api/v1/timetable.ics",
                             "/api/v1/timetable/history", "/api/v1/timetable/history.rss",
                             "/api/v1/neis/schools", "/api/v1/meals") else "other"
    logger.error("request failed route=%s error_type=%s", route, type(exc).__name__)


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

    # Opt-in signed attribution: never trust unsigned XFF/Forwarded on this
    # path, including from the public Funnel that also connects to loopback.
    signing_key = os.environ.get("OPENCIGAN_PROXY_IP_SIGNING_KEY", "")
    if signing_key:
        verified = verify_signed_client_ip(environ, signing_key)
        return verified if verified is not None else str(_clean_ip_str(remote_addr) or remote_addr)

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
    return access_log_admin(method, query_string, request_headers, headers, _access_log_store, _access_log_recorder)


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
    return webhook_api(method, path, body, request_headers, client, headers, _rate_allowed, _webhook_store)


def _suggestion_store():
    global _suggestion_instance
    path = os.environ.get("OPENCIGAN_SUGGESTION_DB", "").strip()
    if os.environ.get("OPENCIGAN_SUGGESTIONS_ENABLED") != "1" or not path:
        return None
    real_path = os.path.normcase(os.path.realpath(path))
    for key in ("OPENCIGAN_HISTORY_DB", "OPENCIGAN_ACCESS_LOG_DB", "OPENCIGAN_ANALYTICS_DB"):
        other = os.environ.get(key, "").strip()
        if other and (real_path == os.path.normcase(os.path.realpath(other)) or
                      (os.path.exists(path) and os.path.exists(other) and os.path.samefile(path, other))):
            return None
    with _suggestion_lock:
        if _suggestion_instance is None or _suggestion_instance.path != path:
            from backend.suggestion_store import SuggestionStore
            _suggestion_instance = SuggestionStore(path)
        return _suggestion_instance


def _timetable_filters(query, require_class=False):
    return timetable_filters(query, require_class, _query_param)


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

    headers = make_response_headers(path, origin, request_origin)

    if method == "OPTIONS":
        return preflight_response(path, headers)

    if client and path in ("/api/v1/admin/analytics", "/api/v1/admin/access-logs"):
        retry = _rate_allowed(("admin", client))
        if retry:
            headers["Retry-After"] = str(retry)
            return json_response(429, headers, {"error": "요청이 너무 많습니다. 잠시 후 다시 시도해 주세요.", "code": "rate_limited"})

    if path == '/api/v1/admin/access-logs':
        status, response_headers, body = _access_log_admin(method, query_string, request_headers, headers)
        response_headers['Content-Length'] = str(len(body))
        return status, response_headers, body

    if path not in ("/api/v1/status", "/api/v1/admin/analytics"):
        allowed, retry_after = (shutter if shutter_instance is None else shutter_instance).check()
        if not allowed:
            headers["Retry-After"] = str(retry_after)
            return json_response(503, headers, {"error": "요청이 집중되어 일시적으로 중단되었습니다. 잠시 후 다시 시도해 주세요.", "code": "service_overloaded", "retry_after": retry_after})

    if path == "/api/v1/webhooks" or path.startswith("/api/v1/webhooks/"):
        return _webhook_api(method, path, request_body, request_headers, client, headers)

    if path in ("/api/v1/suggestions", "/api/v1/admin/suggestions") or path.startswith(("/api/v1/suggestions/", "/api/v1/admin/suggestions/")):
        return suggestion_api(method, path, query_string, request_body, request_headers, client, headers, _rate_allowed, _suggestion_store)

    if path == "/api/v1/analytics/pageview":
        return record_pageview(method, request_body, client, headers, _analytics_store, _rate_allowed)

    if path == "/api/v1/admin/analytics":
        return analytics_summary(method, query_string, request_headers, headers, _analytics_store, _api_recorder, current_cache)

    if method not in ("GET", "HEAD"):
        return json_response(405, headers, {"error": "지원하지 않는 메서드입니다", "code": "method_not_allowed"})

    if client and path != "/api/v1/status":
        retry = _rate_allowed(client)
        if retry:
            headers["Retry-After"] = str(retry)
            return json_response(429, headers, {"error": "요청이 너무 많습니다. 잠시 후 다시 시도해 주세요.", "code": "rate_limited"})
    query = parse_qs(query_string, keep_blank_values=path == "/api/v1/timetable/history.rss")
    try:
        if path == "/api/v1/status":
            result = {"status": "ok", "scope": "process liveness"}
        elif path == "/api/v1/schools":
            result = search_timetable_schools(query, current_cache, _query_param, search_schools)
        elif path == "/api/v1/timetable":
            result = get_timetable(query, current_cache, _query_param, validate_timetable_week, _timetable_filters, _cached_timetable)
        elif path == "/api/v1/timetable.ics":
            return timetable_calendar(query, current_cache, request_headers, headers, _query_param, _timetable_filters, _cached_timetable, render_timetable_ics)
        elif path in ("/api/v1/timetable/history", "/api/v1/timetable/history.rss"):
            result = timetable_history(path, query, request_headers, headers, _query_param, _timetable_filters, _history_store, render_history_feed)
            if isinstance(result, tuple):
                return result
        elif path == "/api/v1/neis/schools":
            result = search_meal_schools(query, current_cache, _query_param, NEISClient)
        elif path == "/api/v1/meals":
            result = get_meals(query, current_cache, _query_param, NEISClient, School)
        else:
            return json_response(404, headers, {"error": "요청한 경로가 없습니다", "code": "not_found"})

        return json_response(200, headers, result)
    except CacheBackoffError as exc:
        if exc.__cause__ is not None:
            _log_request_failure(path, exc.__cause__)
        headers["Retry-After"] = str(exc.retry_after)
        return json_response(503, headers, {"error": "데이터를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.", "code": "upstream_unavailable"})
    except ValueError as exc:
        return json_response(400, headers, {"error": str(exc), "code": "invalid_request"})
    except Exception as exc:
        _log_request_failure(path, exc)
        return json_response(503, headers, {"error": "데이터를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.", "code": "upstream_unavailable"})


_api_recorder = ApiRecorder(_analytics_store)
_access_log_recorder = AccessLogRecorder(_access_log_store)
atexit.register(_access_log_recorder.close)


def dispatch_request(method, path, query_string, cache_instance=None, client=None, request_origin=None, request_body=None, request_headers=None, shutter_instance=None, rate_client=None):
    received_at = datetime.now(timezone(timedelta(hours=9)))
    started = time.perf_counter()
    if rate_client is None:
        rate_client = ("unsigned", client) if client and os.environ.get("OPENCIGAN_PROXY_IP_SIGNING_KEY") else client
    response = _dispatch_request(method, path, query_string, cache_instance, rate_client, request_origin, request_body, request_headers, shutter_instance)
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
            'user_agent': (request_headers or {}).get('User-Agent'),
        }, received_at=received_at)
    return response


class SafeRequestLogging:
    def log_request(self, code="-", size="-"):
        method = self.command if self.command in ("GET", "HEAD", "OPTIONS", "POST", "PUT", "DELETE", "PATCH") else "other"
        logger.info("HTTP request method=%s status=%s", method, code)

    def log_error(self, format, *args):
        logger.warning("HTTP protocol error")


class Handler(SafeRequestLogging, BaseHTTPRequestHandler):
    def _unsupported(self):
        parts = urlsplit(self.path)
        request_body = _read_request_body(self.rfile, self.headers.get("Content-Length")) if (self.command == "POST" and parts.path == "/api/v1/analytics/pageview") or (self.command in ("POST", "PUT", "PATCH") and parts.path.startswith(("/api/v1/webhooks", "/api/v1/suggestions", "/api/v1/admin/suggestions"))) else None
        status_code, headers, body = dispatch_request(self.command, parts.path, parts.query, cache, self.client_address[0], self.headers.get("Origin"), request_body, {"Authorization": self.headers.get("Authorization", ""), "Referer": self.headers.get("Referer", ""), "User-Agent": self.headers.get("User-Agent", "")})
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
        status_code, headers, body = dispatch_request("HEAD", parts.path, parts.query, cache, self.client_address[0], self.headers.get("Origin"), request_headers={"Authorization": self.headers.get("Authorization", ""), "If-None-Match": self.headers.get("If-None-Match", ""), "Referer": self.headers.get("Referer", ""), "User-Agent": self.headers.get("User-Agent", "")})
        self.send_response(status_code)
        for key, val in headers.items():
            self.send_header(key, val)
        self.end_headers()

    def do_GET(self):
        parts = urlsplit(self.path)
        status_code, headers, body = dispatch_request("GET", parts.path, parts.query, cache, self.client_address[0], self.headers.get("Origin"), request_headers={"Authorization": self.headers.get("Authorization", ""), "If-None-Match": self.headers.get("If-None-Match", ""), "Referer": self.headers.get("Referer", ""), "User-Agent": self.headers.get("User-Agent", "")})
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
    201: "201 Created",
    202: "202 Accepted",
    204: "204 No Content",
    304: "304 Not Modified",
    400: "400 Bad Request",
    401: "401 Unauthorized",
    404: "404 Not Found",
    405: "405 Method Not Allowed",
    409: "409 Conflict",
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
        signing_key = os.environ.get("OPENCIGAN_PROXY_IP_SIGNING_KEY", "")
        verified_client = verify_signed_client_ip(environ, signing_key) if signing_key else None
        client = verified_client or resolve_client_ip(environ, trusted_proxies=trusted_proxies)

        status_code, headers, body = dispatch_request(
            method=method,
            path=path,
            query_string=query_string,
            cache_instance=cache_instance,
            client=client,
            rate_client=verified_client,
            request_origin=environ.get("HTTP_ORIGIN"),
            request_body=_read_request_body(environ.get("wsgi.input"), environ.get("CONTENT_LENGTH")) if (method == "POST" and path == "/api/v1/analytics/pageview") or (method in ("POST", "PUT", "PATCH") and path.startswith(("/api/v1/webhooks", "/api/v1/suggestions", "/api/v1/admin/suggestions"))) else None,
            request_headers={"Authorization": environ.get("HTTP_AUTHORIZATION", ""), "If-None-Match": environ.get("HTTP_IF_NONE_MATCH", ""), "Referer": environ.get("HTTP_REFERER", ""), "User-Agent": environ.get("HTTP_USER_AGENT", "")},
        )

        status_line = _STATUS_PHRASES.get(status_code, f"{status_code} Unknown")
        start_response(status_line, list(headers.items()))
        if method == "HEAD":
            return [b""]
        return [body]

    return wsgi_application


app = make_app()
application = app


class SafeWSGIRequestHandler(SafeRequestLogging, wsgiref.simple_server.WSGIRequestHandler):
    pass


class ThreadingWSGIServer(socketserver.ThreadingMixIn, wsgiref.simple_server.WSGIServer):
    daemon_threads = True
    allow_reuse_address = True


def _waitress_proxy_kwargs():
    """Mirror OPENCIGAN_TRUSTED_PROXIES into Waitress proxy settings.

    Waitress drops X-Forwarded-For unless the immediate proxy is trusted
    in its own configuration, so the application-level trust list alone
    never sees the header when serving through a loopback proxy such as
    Tailscale Funnel. Only loopback proxies are mirrored: the server binds
    to loopback, so the immediate peer is always local.
    """
    # Waitress rewrites REMOTE_ADDR from X-Forwarded-For when proxy trust is
    # enabled. Signed mode MUST retain the socket peer, or an unsigned Funnel
    # request can bypass the HMAC fallback via rewritten REMOTE_ADDR.
    if os.environ.get("OPENCIGAN_PROXY_IP_SIGNING_KEY"):
        return {}
    networks = parse_trusted_proxies(os.environ.get("OPENCIGAN_TRUSTED_PROXIES", ""))
    for addr in ("127.0.0.1", "::1"):
        if any(ipaddress.ip_address(addr) in net for net in networks):
            return {
                "trusted_proxy": addr,
                "trusted_proxy_count": 1,
                "trusted_proxy_headers": {"x-forwarded-for"},
            }
    return {}


def serve(host=None, port=None, wsgi_app=None):
    host = host or os.environ.get("HOST", "127.0.0.1")
    port = int(port or os.environ.get("PORT", "8000"))
    target_app = wsgi_app or app

    try:
        import waitress

        threads = int(os.environ.get("THREADS", "8"))
        logger.info("Starting Waitress WSGI server on %s:%s (threads=%d)", host, port, threads)
        waitress.serve(target_app, host=host, port=port, threads=threads, **_waitress_proxy_kwargs())
    except ImportError:
        logger.info("Waitress not installed. Serving with ThreadingWSGIServer on %s:%s", host, port)
        server = wsgiref.simple_server.make_server(
            host, port, target_app, server_class=ThreadingWSGIServer, handler_class=SafeWSGIRequestHandler
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
