import json
import math
import urllib.error
import urllib.parse
import urllib.request
from http.client import HTTPException


class OpensiganError(Exception):
    def __init__(self, message, status=None, code=None, is_timeout=False, is_network_error=False):
        super().__init__(message)
        self.status = status
        self.code = code
        self.is_timeout = is_timeout
        self.is_network_error = is_network_error


def _validate_timeout(timeout):
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
        raise OpensiganError("timeout must be a positive finite number of seconds.", code="invalid_config")
    return timeout


class OpensiganClient:
    def __init__(self, base_url="http://127.0.0.1:8000", timeout=15.0):
        try:
            parts = urllib.parse.urlsplit(base_url)
            valid = (
                parts.scheme in ("http", "https") and parts.hostname
                and parts.username is None and parts.password is None
                and not parts.query and not parts.fragment
                and not any(char.isspace() for char in base_url)
            )
            parts.port
        except (ValueError, TypeError, AttributeError):
            valid = False
        if not valid:
            raise OpensiganError(
                "base_url must be an absolute HTTP(S) URL without credentials, query or fragment.",
                code="invalid_config",
            )
        self.base_url = base_url.rstrip("/")
        self.timeout = _validate_timeout(timeout)

    def _build_url(self, path, params=None):
        query = urllib.parse.urlencode({key: value for key, value in (params or {}).items() if value is not None})
        return f"{self.base_url}{path}" + (f"?{query}" if query else "")

    def _request(self, url, headers=None, timeout=None):
        request = urllib.request.Request(url, headers={"Accept": "application/json", **(headers or {})}, method="GET")
        timeout = _validate_timeout(self.timeout if timeout is None else timeout)
        try:
            try:
                response = urllib.request.urlopen(request, timeout=timeout)
            except urllib.error.HTTPError as error:
                response = error
            with response:
                return response.code, response.headers, response.read()
        except TimeoutError:
            raise OpensiganError("Request timed out.", is_timeout=True) from None
        except urllib.error.URLError as error:
            if isinstance(error.reason, TimeoutError):
                raise OpensiganError("Request timed out.", is_timeout=True) from None
            raise OpensiganError("Unable to connect to the API.", is_network_error=True) from None
        except (OSError, HTTPException):
            raise OpensiganError("Unable to connect to the API or read its response.", is_network_error=True) from None

    def _parse_json(self, body, status):
        try:
            parsed = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            if 200 <= status < 300:
                raise OpensiganError("Response is not valid UTF-8 JSON.", status=status, code="invalid_response") from None
            parsed = None
        if not 200 <= status < 300:
            code = parsed.get("code") if isinstance(parsed, dict) else None
            message = parsed.get("error") if isinstance(parsed, dict) else None
            raise OpensiganError(
                message if isinstance(message, str) else f"Request failed (HTTP {status}).",
                status=status, code=code if isinstance(code, str) else None,
            )
        if not isinstance(parsed, dict):
            raise OpensiganError("Response must be a JSON object.", status=status, code="invalid_response")
        return parsed

    def _get_json(self, path, params=None, timeout=None):
        status, _, body = self._request(self._build_url(path, params), timeout=timeout)
        return self._parse_json(body, status)

    def get_status(self, timeout=None):
        return self._get_json("/api/v1/status", timeout=timeout)

    def search_schools(self, query, timeout=None):
        return self._get_json("/api/v1/schools", {"q": query.strip()}, timeout=timeout)

    def search_neis_schools(self, query, timeout=None):
        return self._get_json("/api/v1/neis/schools", {"q": query.strip()}, timeout=timeout)

    def get_timetable(self, school, week, grade=None, classroom=None, teacher=None, timeout=None):
        return self._get_json("/api/v1/timetable", {
            "school": school.strip(), "week": week.strip(),
            "grade": grade, "class": classroom, "teacher": teacher,
        }, timeout=timeout)

    def get_timetable_ics_url(self, school, grade, classroom, weeks=1, mode="periods", teacher=None, times=None):
        return self._build_url("/api/v1/timetable.ics", {
            "school": school.strip(), "grade": grade, "class": classroom,
            "weeks": weeks, "mode": mode, "teacher": teacher, "times": times,
        })

    def get_timetable_ics(
        self, school, grade, classroom, weeks=1, mode="periods",
        teacher=None, if_none_match=None, timeout=None, times=None,
    ):
        """Return (UTF-8 calendar text or None, not_modified, etag)."""
        url = self.get_timetable_ics_url(school, grade, classroom, weeks, mode, teacher, times=times)
        headers = {"Accept": "text/calendar"}
        if if_none_match:
            headers["If-None-Match"] = if_none_match
        status, response_headers, body = self._request(url, headers=headers, timeout=timeout)
        etag = response_headers.get("ETag")
        if status == 304:
            return None, True, etag
        if not 200 <= status < 300:
            self._parse_json(body, status)
        try:
            return body.decode("utf-8"), False, etag
        except UnicodeDecodeError:
            raise OpensiganError("Response is not valid UTF-8.", status=status, code="invalid_response") from None

    def get_meals(self, school, from_date, to_date, timeout=None):
        return self._get_json("/api/v1/meals", {
            "school": school.strip(), "from": from_date.strip(), "to": to_date.strip(),
        }, timeout=timeout)

    def get_timetable_history(self, school, week, cursor=None, timeout=None):
        return self._get_json("/api/v1/timetable/history", {
            "school": school.strip(), "week": week.strip(), "cursor": cursor,
        }, timeout=timeout)
