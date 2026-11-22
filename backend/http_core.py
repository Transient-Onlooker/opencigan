import json
import re


def make_response_headers(path, origin, request_origin):
    headers = {"Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store"}
    if origin:
        headers["Vary"] = "Origin"
    if origin and (request_origin is None or request_origin in [item.strip() for item in origin.split(",")]):
        headers["Access-Control-Allow-Origin"] = request_origin or origin.split(",")[0].strip()
        headers["Access-Control-Expose-Headers"] = "Retry-After, ETag" if path in ("/api/v1/timetable.ics", "/api/v1/timetable/history.rss") else "Retry-After"
    return headers


def preflight_response(path, headers):
    if path == "/api/v1/admin/suggestions" or path.startswith("/api/v1/admin/suggestions/"):
        headers["Access-Control-Allow-Methods"] = "GET, HEAD, PATCH, DELETE, OPTIONS"
    else:
        headers["Access-Control-Allow-Methods"] = "GET, HEAD, POST, PUT, DELETE, OPTIONS" if path.startswith("/api/v1/webhooks") else "GET, HEAD, POST, OPTIONS"
    headers["Access-Control-Allow-Headers"] = (
        "Content-Type, Authorization, If-None-Match" if path in ("/api/v1/timetable.ics", "/api/v1/timetable/history.rss")
        else "Content-Type, Authorization"
    )
    headers["Content-Length"] = "0"
    return 204, headers, b""


def json_response(status, headers, payload):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers["Content-Length"] = str(len(body))
    return status, headers, body


def query_param(params, key, limit):
    values = params.get(key, [])
    if len(values) != 1 or not values[0].strip() or len(values[0]) > limit:
        raise ValueError(f"{key} 값이 올바르지 않습니다")
    return values[0].strip()


def timetable_filters(query, require_class=False, query_value=query_param):
    grade_filter = None
    class_filter = None
    teacher_filter = None
    if require_class or "grade" in query:
        raw_grade = query_value(query, "grade", 1)
        if not re.fullmatch(r"[1-6]", raw_grade):
            raise ValueError("grade는 1부터 6까지의 정수여야 합니다")
        grade_filter = int(raw_grade)
    if require_class or "class" in query:
        raw_class = query_value(query, "class", 2)
        if not re.fullmatch(r"[1-9][0-9]?", raw_class):
            raise ValueError("class는 1부터 99까지의 정수여야 합니다")
        class_filter = int(raw_class)
    if "teacher" in query:
        teacher_filter = query_value(query, "teacher", 50).casefold()
    return grade_filter, class_filter, teacher_filter
