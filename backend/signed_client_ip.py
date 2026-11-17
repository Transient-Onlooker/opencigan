"""Verify HMAC-signed visitor IP attribution without trusting forwarded headers."""

import hashlib
import hmac
import ipaddress
import re
import time


def verify_signed_client_ip(environ, secret, *, now=None):
    """HMAC-SHA256 over LF-separated METHOD, PATH, RAW_QUERY, IP, UNIX_SECONDS."""
    if not isinstance(secret, str) or len(secret.encode("utf-8")) < 32:
        return None
    ip_raw = environ.get("HTTP_X_OPENCIGAN_CLIENT_IP", "")
    timestamp = environ.get("HTTP_X_OPENCIGAN_IP_TIMESTAMP", "")
    signature = environ.get("HTTP_X_OPENCIGAN_IP_SIGNATURE", "")
    if not all(isinstance(s, str) for s in (ip_raw, timestamp, signature)):
        return None
    if len(ip_raw) > 45 or not re.fullmatch(r"[0-9]{10,12}", timestamp):
        return None
    if not re.fullmatch(r"[0-9a-fA-F]{64}", signature):
        return None
    if abs((time.time() if now is None else now) - int(timestamp)) > 60:
        return None
    try:
        ip = ipaddress.ip_address(ip_raw)
    except ValueError:
        return None
    method, path, query = (
        environ.get("REQUEST_METHOD", ""),
        environ.get("PATH_INFO", ""),
        environ.get("QUERY_STRING", ""),
    )
    if not all(isinstance(s, str) for s in (method, path, query)):
        return None
    if not method or not path.startswith("/") or any("\n" in s for s in (method, path, query)):
        return None
    content = "\n".join((method.upper(), path, query, ip_raw, timestamp)).encode("utf-8")
    expected = hmac.new(secret.encode("utf-8"), content, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature.lower()):
        return None
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        return str(ip.ipv4_mapped)
    return str(ip)
