import json


def json_response(status, headers, payload):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers["Content-Length"] = str(len(body))
    return status, headers, body
