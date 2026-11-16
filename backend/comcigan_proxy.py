import os
import threading
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, build_opener

_lock = threading.Lock()
_configured = False


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
            request.set_proxy(parsed.netloc, "http")
            return opener.open(request, timeout=timeout)

        helpers.urlopen = open_comcigan
        _configured = True
