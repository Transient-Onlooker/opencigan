import json
import re
import sqlite3
from backend.http_core import json_response


def webhook_api(method, path, body, request_headers, client, headers, rate_allowed, webhook_store):
    from backend.webhook_store import SubscriptionLimitError

    def respond(status, payload):
        return json_response(status, headers, payload)

    if client:
        retry = rate_allowed(("webhooks", client))
        if retry:
            headers["Retry-After"] = str(retry)
            return respond(429, {"error": "요청이 너무 많습니다", "code": "rate_limited"})
    if len(body or b"") > 4096:
        return respond(413, {"error": "요청 본문이 너무 큽니다", "code": "payload_too_large"})
    try:
        store = webhook_store()
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
        match = re.fullmatch(r"/api/v1/webhooks/([A-Za-z0-9_-]{24})(/deliveries|/test|/rotate|/template(?:/preview)?)?", path)
        if not match:
            return respond(404, {"error": "요청한 경로가 없습니다", "code": "not_found"})
        if method not in ("GET", "HEAD", "DELETE", "POST", "PUT"):
            return respond(405, {"error": "지원하지 않는 메서드입니다", "code": "method_not_allowed"})
        authorization = (request_headers or {}).get("Authorization", "")
        token = authorization[7:] if authorization.startswith("Bearer ") else ""
        identifier = match.group(1)
        if match.group(2) == "/template/preview":
            if method != "POST":
                return respond(405, {"error": "method not allowed", "code": "method_not_allowed"})
            payload = json.loads(body or b"{}")
            if not isinstance(payload, dict) or set(payload) != {"template", "discordEmbed"}:
                raise ValueError("invalid payload")
            result = store.preview_template(identifier, token, payload["template"], payload["discordEmbed"])
            result = {"payload": result} if result is not None else None
        elif match.group(2) == "/template":
            if method == "GET" or method == "HEAD":
                result = store.get_template(identifier, token)
            elif method == "PUT":
                payload = json.loads(body or b"{}")
                if not isinstance(payload, dict) or set(payload) != {"template", "discordEmbed"}:
                    raise ValueError("invalid payload")
                result = store.update_template(identifier, token, payload["template"], payload["discordEmbed"])
            elif method == "DELETE":
                result = {"reset": True} if store.reset_template(identifier, token) else None
            else:
                return respond(405, {"error": "method not allowed", "code": "method_not_allowed"})
        elif match.group(2) == "/rotate":
            if method != "POST":
                return respond(405, {"error": "지원하지 않는 메서드입니다", "code": "method_not_allowed"})
            payload = json.loads(body or b"{}")
            if not isinstance(payload, dict) or set(payload) != {"newToken"}:
                raise ValueError("invalid payload")
            result = store.rotate(identifier, token, payload["newToken"])
        elif match.group(2) == "/test":
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
