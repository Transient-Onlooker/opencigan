import json


def make_response_headers(path, origin, request_origin):
    headers = {"Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store"}
    if origin:
        headers["Vary"] = "Origin"
    if origin and (request_origin is None or request_origin in [item.strip() for item in origin.split(",")]):
        headers["Access-Control-Allow-Origin"] = request_origin or origin.split(",")[0].strip()
        headers["Access-Control-Expose-Headers"] = "Retry-After, ETag" if path in ("/api/v1/timetable.ics", "/api/v1/timetable/history.rss") else "Retry-After"
    return headers


def preflight_response(path, headers):
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
