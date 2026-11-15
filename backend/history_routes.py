import hashlib
import re
from datetime import date, datetime, timedelta, timezone

from backend.http_core import json_response

def timetable_history(path, query, request_headers, headers, query_param, timetable_filters, history_store, render_feed):
    school = query_param(query, "school", 100)
    if not re.fullmatch(r"[0-9]+:[^:]{1,50}", school):
        raise ValueError("학교 식별자가 올바르지 않습니다")
    if path.endswith(".rss") and "week" not in query:
        now = datetime.now(timezone(timedelta(hours=9))).date()
        week = (now - timedelta(days=now.weekday())).isoformat()
    else:
        week = query_param(query, "week", 10)
    parsed_week = date.fromisoformat(week)
    if parsed_week.isoformat() != week or parsed_week.weekday() != 0:
        raise ValueError("주 시작일이 올바르지 않습니다")
    cursor = query_param(query, "cursor", 100) if "cursor" in query else None
    store = history_store()
    if store is None:
        return json_response(503, headers, {"error": "변경 이력 저장이 활성화되지 않았습니다", "code": "history_disabled"})
    if path.endswith(".rss"):
        grade_filter, class_filter, _ = timetable_filters({key: value for key, value in query.items() if key != "teacher"}, require_class=True)
        if cursor is not None:
            raise ValueError("피드에는 커서를 사용할 수 없습니다")
        filters = {key: query_param(query, key, 50) for key in ("subject", "teacher") if key in query}
        if "weekday" in query:
            filters["weekday"] = query_param(query, "weekday", 1)
            if filters["weekday"] not in ("1", "2", "3", "4", "5"):
                raise ValueError("weekday는 1(월)부터 5(금)까지여야 합니다")
        if "period" in query:
            raw_period = query_param(query, "period", 2)
            if not re.fullmatch(r"(?:[1-9]|1[0-9]|20)", raw_period):
                raise ValueError("period는 1부터 20까지여야 합니다")
            filters["period"] = int(raw_period)
        if "type" in query:
            filters["type"] = query_param(query, "type", 7)
            if filters["type"] not in ("added", "deleted", "changed"):
                raise ValueError("type이 올바르지 않습니다")
        group = query_param(query, "group", 7) if "group" in query else "changes"
        if group not in ("changes", "daily"):
            raise ValueError("group은 changes 또는 daily여야 합니다")
        changes = store.list(school, week, grade=grade_filter, classroom=class_filter, include_ids=True, filters=filters)["changes"]
        body = render_feed(school, grade_filter, class_filter, changes, group=group)
        etag = '"' + hashlib.sha256(body).hexdigest() + '"'
        headers.update({"Content-Type": "application/rss+xml; charset=utf-8", "ETag": etag,
                        "Cache-Control": "private, max-age=0, must-revalidate"})
        validators = (request_headers or {}).get("If-None-Match", "").strip()
        if validators == "*" or etag in (tag.strip().removeprefix("W/") for tag in validators.split(",")):
            return 304, headers, b""
        headers["Content-Length"] = str(len(body))
        return 200, headers, body
    return store.list(school, week, cursor=cursor)
