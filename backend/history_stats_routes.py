import hmac
import os
import re
import sqlite3
from datetime import date
from urllib.parse import parse_qs

from backend.http_core import json_response


def history_stats(method, query_string, request_headers, headers, history_store):
    def respond(status, error, code):
        return json_response(status, headers, {"error": error, "code": code})

    if os.environ.get("OPENCIGAN_HISTORY_STATS_ENABLED") != "1":
        return respond(503, "변경 통계가 비활성화되어 있습니다", "history_stats_disabled")
    if method not in ("GET", "HEAD"):
        return respond(405, "지원하지 않는 메서드입니다", "method_not_allowed")
    token = os.environ.get("OPENCIGAN_ANALYTICS_ADMIN_TOKEN", "")
    supplied = (request_headers or {}).get("Authorization", "")
    if not token or not hmac.compare_digest(supplied.encode(), ("Bearer " + token).encode()):
        headers["WWW-Authenticate"] = 'Bearer realm="OpenCigan analytics"'
        return respond(401, "인증이 필요합니다", "unauthorized")
    try:
        query = parse_qs(query_string, keep_blank_values=True, max_num_fields=2)
        if set(query) != {"school", "week"} or any(len(value) != 1 for value in query.values()):
            raise ValueError("invalid query")
        school, week = query["school"][0], query["week"][0]
        if len(school) > 100 or not re.fullmatch(r"[0-9]+:[^:\x00-\x1f\x7f]{1,50}", school):
            raise ValueError("invalid school")
        parsed = date.fromisoformat(week)
        if parsed.isoformat() != week or parsed.weekday() != 0:
            raise ValueError("invalid week")
        store = history_store()
        if store is None:
            return respond(503, "변경 이력 저장이 비활성화되어 있습니다", "history_disabled")
        return json_response(200, headers, store.change_stats(school, week))
    except (ValueError, TypeError):
        return respond(400, "조회 조건이 올바르지 않습니다", "invalid_request")
    except (OSError, sqlite3.Error):
        return respond(503, "변경 통계를 불러오지 못했습니다", "history_stats_unavailable")
