import os
import logging
import threading
import time
from contextvars import ContextVar
from functools import wraps
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, build_opener

_lock = threading.Lock()
_configured = False
logger = logging.getLogger("opensigan.comcigan_proxy")
_deadline = ContextVar("comcigan_deadline", default=None)
UPSTREAM_BUDGET_SECONDS = 35


def with_comcigan_budget(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        if _deadline.get() is not None:
            return function(*args, **kwargs)
        token = _deadline.set(time.monotonic() + UPSTREAM_BUDGET_SECONDS)
        try:
            return function(*args, **kwargs)
        finally:
            _deadline.reset(token)
    return wrapped


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def configure_comcigan_proxy():
    global _configured
    proxy = os.environ.get("OPENCIGAN_COMCIGAN_PROXY", "").strip()
    if not proxy:
        return
    parsed = urlsplit(proxy)
    if (parsed.scheme != "http" or parsed.hostname not in ("127.0.0.1", "::1", "localhost")
            or not parsed.port or parsed.username or parsed.password
            or parsed.path not in ("", "/") or parsed.query or parsed.fragment):
        raise ValueError("OPENCIGAN_COMCIGAN_PROXY must be a local HTTP proxy URL")
    with _lock:
        if _configured:
            return
        import pycomcigan.helpers as helpers

        opener = build_opener(ProxyHandler({}), _NoRedirect())

        def open_comcigan(request, timeout=30):
            target = urlsplit(request.full_url)
            if target.scheme != "http" or target.hostname != "comci.net" or target.port != 4082:
                raise ValueError("Unexpected Comcigan request target")
            deadline = _deadline.get()
            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("Comcigan request budget exhausted")
                timeout = min(timeout, remaining)
            request.set_proxy(parsed.netloc, "http")
            stage = "service_page" if target.path == "/st" else "data"
            started = time.monotonic()
            result = "other_error"
            try:
                response = opener.open(request, timeout=timeout)
                result = "success"
                return response
            except HTTPError as error:
                result = "http_error"
                if error.code in (403, 429):
                    logger.warning("comcigan request rejected upstream_http_status=%s", error.code)
                raise
            except URLError as error:
                result = "timeout" if isinstance(error.reason, TimeoutError) else "network_error"
                raise
            except TimeoutError:
                result = "timeout"
                raise
            except OSError:
                result = "network_error"
                raise
            finally:
                logger.info("comcigan response headers stage=%s duration_ms=%.1f result=%s timeout_s=%s", stage, (time.monotonic() - started) * 1000, result, timeout)

        helpers.urlopen = open_comcigan
        _configured = True
