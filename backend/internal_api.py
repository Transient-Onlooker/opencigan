"""Loopback-only, independently served timetable API."""
import hmac
import json
import logging
import os
from urllib.parse import parse_qs

from backend.timetable import fetch_timetable

logger = logging.getLogger(__name__)


def application(environ, start_response):
    token = os.environ.get("OPENCIGAN_INTERNAL_TOKEN", "")
    provided = environ.get("HTTP_AUTHORIZATION", "")
    if not token or not hmac.compare_digest(provided.encode(), ("Bearer " + token).encode()):
        status, payload = "401 Unauthorized", {"code": "unauthorized", "error": "Unauthorized"}
    elif environ.get("PATH_INFO") != "/internal/v1/timetable":
        status, payload = "404 Not Found", {"code": "not_found", "error": "Not found"}
    elif environ.get("REQUEST_METHOD") != "GET":
        status, payload = "405 Method Not Allowed", {"code": "method_not_allowed", "error": "Method not allowed"}
    else:
        params = parse_qs(environ.get("QUERY_STRING", ""), keep_blank_values=True)
        if set(params) != {"school", "week"} or any(len(v) != 1 for v in params.values()):
            status, payload = "400 Bad Request", {"code": "invalid_request", "error": "Invalid query"}
        else:
            try:
                payload = fetch_timetable(params["school"][0], params["week"][0], include_original=True)
                status = "200 OK"
            except ValueError:
                status, payload = "400 Bad Request", {"code": "invalid_request", "error": "Invalid query"}
            except Exception:
                logger.exception("Internal timetable lookup failed")
                status, payload = "503 Service Unavailable", {"code": "upstream_unavailable", "error": "Timetable unavailable"}
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    start_response(status, [("Content-Type", "application/json; charset=utf-8"),
                            ("Cache-Control", "no-store"), ("Content-Length", str(len(body)))])
    return [body]


if __name__ == "__main__":
    if not os.environ.get("OPENCIGAN_INTERNAL_TOKEN"):
        raise SystemExit("OPENCIGAN_INTERNAL_TOKEN is required")
    from waitress import serve
    serve(application, host="127.0.0.1", port=8001, threads=2, connection_limit=32)
