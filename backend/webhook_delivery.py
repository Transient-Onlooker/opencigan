"""Bounded, signed delivery primitives for supported webhook providers."""

import hashlib
import hmac
import math
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import parse_qs, urlsplit

import requests


def validate_destination(url):
    if not isinstance(url, str) or len(url) > 2048 or any(c.isspace() or ord(c) < 32 for c in url):
        raise ValueError("invalid webhook URL")
    try:
        parts = urlsplit(url)
        if parts.scheme != "https" or parts.username is not None or parts.password is not None or parts.port not in (None, 443) or parts.fragment:
            raise ValueError("invalid webhook URL")
    except ValueError:
        raise ValueError("invalid webhook URL") from None
    if parts.hostname in ("discord.com", "discordapp.com"):
        if not re.fullmatch(r"/api/webhooks/[0-9]{1,30}/[A-Za-z0-9_-]{1,200}", parts.path) or parts.query:
            raise ValueError("invalid Discord webhook URL")
        return "discord"
    if parts.hostname == "chat.googleapis.com":
        try:
            query = parse_qs(parts.query, keep_blank_values=True, strict_parsing=True)
        except ValueError:
            raise ValueError("invalid Google Chat webhook URL") from None
        if not re.fullmatch(r"/v1/spaces/[A-Za-z0-9_-]{1,128}/messages", parts.path) or set(query) != {"key", "token"} or any(len(values) != 1 or not values[0] for values in query.values()):
            raise ValueError("invalid Google Chat webhook URL")
        return "google-chat"
    raise ValueError("unsupported webhook host")


def signature(secret, body):
    if not isinstance(secret, bytes) or len(secret) < 32 or not isinstance(body, bytes):
        raise ValueError("invalid signature input")
    return "sha256=" + hmac.new(secret, body, hashlib.sha256).hexdigest()


def send_webhook(url, body, secret, event_id, session_factory=requests.Session):
    validate_destination(url)
    if not isinstance(event_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", event_id):
        raise ValueError("invalid event ID")
    if not isinstance(body, bytes) or len(body) > 65536:
        raise ValueError("invalid webhook body")
    headers = {"Content-Type": "application/json", "X-OpenCigan-Event-Id": event_id,
               "X-OpenCigan-Signature": signature(secret, body)}
    with session_factory() as session:
        session.trust_env = False
        try:
            response = session.post(url, data=body, headers=headers, timeout=(3, 5), allow_redirects=False, stream=True)
            status = response.status_code
            retry_after = response.headers.get("Retry-After", "")
            response.close()
        except requests.RequestException:
            return {"delivered": False, "retryable": True, "status": None, "retryAfter": None}
    delay = None
    if isinstance(retry_after, str) and len(retry_after) <= 12 and re.fullmatch(r"[0-9]{1,6}(?:\.[0-9]{1,6})?", retry_after, re.ASCII):
        delay = min(math.ceil(float(retry_after)), 3600)
    elif isinstance(retry_after, str) and len(retry_after) <= 64:
        try:
            parsed = parsedate_to_datetime(retry_after)
            if parsed.tzinfo is not None:
                delay = min(3600, max(0, math.ceil((parsed - datetime.now(timezone.utc)).total_seconds())))
        except (TypeError, ValueError, OverflowError):
            pass
    return {"delivered": 200 <= status < 300, "retryable": status in (408, 429) or status >= 500,
            "status": status, "retryAfter": delay}
