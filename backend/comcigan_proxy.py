import os
import logging
import http.client
import socket
import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPHandler, HTTPRedirectHandler, ProxyHandler, build_opener

_lock = threading.Lock()
_configured = False
logger = logging.getLogger("opensigan.comcigan_proxy")
_deadline = ContextVar("comcigan_deadline", default=None)
UPSTREAM_BUDGET_SECONDS = 35


@contextmanager
def acquire_with_comcigan_budget(lock):
    deadline = _deadline.get()
    if deadline is None:
        acquired = lock.acquire()
    else:
        remaining = deadline - time.monotonic()
        acquired = remaining > 0 and lock.acquire(timeout=remaining)
    if not acquired:
        raise TimeoutError("Comcigan request budget exhausted while waiting for protocol")
    try:
        if deadline is not None and time.monotonic() >= deadline:
            raise TimeoutError("Comcigan request budget exhausted while waiting for protocol")
        yield
    finally:
        lock.release()


def _run_with_deadline(response, deadline, operation):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("Comcigan request budget exhausted")
    try:
        sock = response.fp.raw._sock
    except AttributeError as error:
        raise RuntimeError("Cannot enforce Comcigan response deadline") from error
    if not isinstance(sock, socket.socket):
        raise RuntimeError("Cannot enforce Comcigan response deadline")
    expired = threading.Event()
    finished = threading.Event()
    timer_lock = threading.Lock()

    def interrupt():
        with timer_lock:
            if finished.is_set():
                return
            expired.set()
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    timer = threading.Timer(remaining, interrupt)
    timer.daemon = True
    timer.start()
    try:
        result = operation()
    except BaseException as error:
        with timer_lock:
            finished.set()
            timer.cancel()
            timed_out = expired.is_set()
        if timed_out and isinstance(error, Exception):
            raise TimeoutError("Comcigan request budget exhausted") from error
        raise
    with timer_lock:
        finished.set()
        timer.cancel()
        timed_out = expired.is_set() or time.monotonic() >= deadline
    if timed_out:
        raise TimeoutError("Comcigan request budget exhausted")
    return result


class _DeadlineHTTPResponse(http.client.HTTPResponse):
    def begin(self):
        deadline = _deadline.get()
        if deadline is None:
            return super().begin()
        return _run_with_deadline(self, deadline, super().begin)


class _DeadlineHTTPConnection(http.client.HTTPConnection):
    response_class = _DeadlineHTTPResponse


class _DeadlineHTTPHandler(HTTPHandler):
    def http_open(self, request):
        return self.do_open(_DeadlineHTTPConnection, request)


class _DeadlineResponse:
    """Enforce the shared budget while the parser reads the response body."""

    def __init__(self, response, deadline):
        self._response = response
        self._deadline = deadline

    def __getattr__(self, name):
        return getattr(self._response, name)

    def __enter__(self):
        self._response.__enter__()
        return self

    def __exit__(self, *args):
        return self._response.__exit__(*args)

    def read(self, *args, **kwargs):
        if self._response.fp is None:
            return self._response.read(*args, **kwargs)
        return _run_with_deadline(self._response, self._deadline, lambda: self._response.read(*args, **kwargs))


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

        opener = build_opener(ProxyHandler({}), _NoRedirect(), _DeadlineHTTPHandler())

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
                return _DeadlineResponse(response, deadline) if deadline is not None else response
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
