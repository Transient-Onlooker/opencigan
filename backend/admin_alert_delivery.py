"""Bounded delivery for explicitly configured administrator alerts."""

import json

from backend.webhook_delivery import send_webhook, validate_destination


def send_admin_alert(destination, secret, event_id, kind, status_group=None, *, send=send_webhook):
    provider = validate_destination(destination)
    if kind not in {"status_errors", "request_volume", "error_ratio", "school_scan"}:
        raise ValueError("invalid alert kind")
    if kind == "status_errors":
        if status_group not in {"404", "429", "5xx"}:
            raise ValueError("invalid alert status group")
        detail = f" ({status_group})"
    else:
        if status_group is not None:
            raise ValueError("unexpected alert status group")
        detail = ""
    text = f"OpenCigan 관리자 알림: 이상 접근 검토가 필요합니다.{detail} 관리자 화면에서 확인하세요."
    payload = {"content": text, "allowed_mentions": {"parse": []}} if provider == "discord" else {"text": text}
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return send(destination, body, secret, event_id)
