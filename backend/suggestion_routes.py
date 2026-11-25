"""Anonymous feature-suggestion API routes (ST-05).

Provides HTTP handler for feature suggestions:
- Anonymous submission of suggestions (pending by default, returns 201 Created)
- Submitter self-service retrieval using opaque token
- Unauthenticated search of approved suggestions only
- Admin operations (list, transition, delete) protected by Bearer token
  with a minimum length; the configured token must also be random
- Strict input/body bounds and rate limiting
- Safe error codes and no client IP logging/storage
"""

import hmac
import json
import os
import re
import sqlite3
from urllib.parse import parse_qs

from backend.http_core import json_response
from backend.suggestion_store import (
    ADMIN_TRANSITIONS,
    CONTEXT_MAX_LENGTH,
    DESCRIPTION_MAX_LENGTH,
    SUBMIT_BODY_MAX_BYTES,
    SuggestionDuplicateError,
    SuggestionLimitError,
    SuggestionStore,
    TITLE_MAX_LENGTH,
    VALID_STATUSES,
)

_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{24}$")
_ALLOWED_STATUSES = set(VALID_STATUSES)
_MIN_ADMIN_TOKEN_LEN = 16


def _check_admin_auth(request_headers, headers):
    """Verify the configured admin bearer token."""
    admin_token = os.environ.get("OPENCIGAN_ADMIN_TOKEN", "").strip()
    if not admin_token or len(admin_token) < _MIN_ADMIN_TOKEN_LEN:
        headers["WWW-Authenticate"] = 'Bearer realm="Suggestion admin"'
        return False

    supplied = (request_headers or {}).get("Authorization", "")
    expected = f"Bearer {admin_token}".encode("utf-8")
    if not hmac.compare_digest(supplied.encode("utf-8"), expected):
        headers["WWW-Authenticate"] = 'Bearer realm="Suggestion admin"'
        return False

    return True


def suggestion_api(
    method,
    path,
    query_string,
    body,
    request_headers,
    client,
    headers,
    rate_allowed,
    suggestion_store,
):
    """Dispatch suggestion API requests for public and admin endpoints."""
    def respond(status, payload):
        return json_response(status, headers, payload)

    # 1. Rate limiting
    if client:
        retry = rate_allowed(("suggestions", client))
        if retry:
            headers["Retry-After"] = str(retry)
            return respond(
                429,
                {"error": "요청이 너무 많습니다", "code": "rate_limited"},
            )

    # 2. Body size check (SUBMIT_BODY_MAX_BYTES = 4096)
    if len(body or b"") > SUBMIT_BODY_MAX_BYTES:
        return respond(
            413,
            {"error": "요청 본문이 너무 큽니다", "code": "payload_too_large"},
        )

    try:
        # 3. Store availability check
        store = suggestion_store()
        if store is None:
            return respond(
                503,
                {
                    "error": "제안 기능이 활성화되지 않았습니다",
                    "code": "suggestions_disabled",
                },
            )

        # 4. Route matching
        # 4A. /api/v1/suggestions (Public collection)
        if path == "/api/v1/suggestions":
            if method == "POST":
                try:
                    payload = json.loads(body or b"{}")
                except (ValueError, TypeError, UnicodeDecodeError):
                    return respond(
                        400,
                        {
                            "error": "요청 값이 올바르지 않습니다",
                            "code": "invalid_request",
                        },
                    )
                if not isinstance(payload, dict):
                    return respond(
                        400,
                        {
                            "error": "요청 값이 올바르지 않습니다",
                            "code": "invalid_request",
                        },
                    )
                allowed_keys = {"title", "description", "context"}
                if not set(payload).issubset(allowed_keys) or "title" not in payload or "description" not in payload:
                    return respond(
                        400,
                        {
                            "error": "요청 값이 올바르지 않습니다",
                            "code": "invalid_request",
                        },
                    )
                res = store.create(
                    payload.get("title"),
                    payload.get("description"),
                    payload.get("context"),
                )
                return respond(201, res)

            elif method in ("GET", "HEAD"):
                # Approved-only public search
                try:
                    values = parse_qs(query_string or "", keep_blank_values=True, max_num_fields=10)
                except ValueError:
                    return respond(
                        400,
                        {
                            "error": "요청 값이 올바르지 않습니다",
                            "code": "invalid_request",
                        },
                    )
                allowed_params = {"q", "cursor", "limit"}
                if set(values) - allowed_params or any(len(items) != 1 for items in values.values()):
                    return respond(
                        400,
                        {
                            "error": "요청 값이 올바르지 않습니다",
                            "code": "invalid_request",
                        },
                    )
                raw_q = values.get("q", [None])[0]
                raw_cursor = values.get("cursor", [None])[0]
                raw_limit = values.get("limit", [None])[0]

                if raw_q is not None and len(raw_q) > 100:
                    return respond(
                        400,
                        {
                            "error": "검색어는 100자 이하여야 합니다",
                            "code": "invalid_request",
                        },
                    )

                if raw_cursor is not None and (not raw_cursor.isascii() or not raw_cursor.isdigit() or len(raw_cursor) > 19 or not 1 <= int(raw_cursor) <= 9223372036854775807):
                    return respond(
                        400,
                        {
                            "error": "커서가 올바르지 않습니다",
                            "code": "invalid_request",
                        },
                    )

                limit = 20
                if raw_limit is not None:
                    if not raw_limit.isdigit() or not 1 <= int(raw_limit) <= 100:
                        return respond(
                            400,
                            {
                                "error": "조회 건수는 1~100 사이여야 합니다",
                                "code": "invalid_request",
                            },
                        )
                    limit = int(raw_limit)

                res = store.search_approved(query=raw_q, cursor=raw_cursor, limit=limit)
                return respond(200, res)

            else:
                return respond(
                    405,
                    {"error": "지원하지 않는 메서드입니다", "code": "method_not_allowed"},
                )

        # 4B. /api/v1/suggestions/<id> (Author self-service)
        match_item = _ID_PATTERN.fullmatch(path[len("/api/v1/suggestions/"):]) if path.startswith("/api/v1/suggestions/") else None
        if match_item:
            if method not in ("GET", "HEAD"):
                return respond(
                    405,
                    {"error": "지원하지 않는 메서드입니다", "code": "method_not_allowed"},
                )
            identifier = path[len("/api/v1/suggestions/"):]
            authorization = (request_headers or {}).get("Authorization", "")
            token = authorization[7:].strip() if authorization.startswith("Bearer ") else ""
            if not token:
                headers["WWW-Authenticate"] = 'Bearer realm="Suggestion author"'
                return respond(
                    401,
                    {"error": "인증이 필요합니다", "code": "unauthorized"},
                )
            suggestion = store.get_own(identifier, token)
            if suggestion is None:
                headers["WWW-Authenticate"] = 'Bearer realm="Suggestion author"'
                return respond(
                    401,
                    {"error": "인증이 필요합니다", "code": "unauthorized"},
                )
            return respond(200, suggestion)

        # 4C. /api/v1/admin/suggestions (Admin listing)
        if path == "/api/v1/admin/suggestions":
            if not _check_admin_auth(request_headers, headers):
                return respond(
                    401,
                    {"error": "인증이 필요합니다", "code": "unauthorized"},
                )

            if method not in ("GET", "HEAD"):
                return respond(
                    405,
                    {"error": "지원하지 않는 메서드입니다", "code": "method_not_allowed"},
                )

            try:
                values = parse_qs(query_string or "", keep_blank_values=True, max_num_fields=10)
            except ValueError:
                return respond(
                    400,
                    {
                        "error": "요청 값이 올바르지 않습니다",
                        "code": "invalid_request",
                    },
                )
            allowed_params = {"status", "cursor", "limit"}
            if set(values) - allowed_params or any(len(items) != 1 for items in values.values()):
                return respond(
                    400,
                    {
                        "error": "요청 값이 올바르지 않습니다",
                        "code": "invalid_request",
                    },
                )
            raw_status = values.get("status", [None])[0]
            raw_cursor = values.get("cursor", [None])[0]
            raw_limit = values.get("limit", [None])[0]

            if raw_status is not None and raw_status not in _ALLOWED_STATUSES:
                return respond(
                    400,
                    {
                        "error": "상태 필터가 올바르지 않습니다",
                        "code": "invalid_request",
                    },
                )

            if raw_cursor is not None and (not raw_cursor.isascii() or not raw_cursor.isdigit() or len(raw_cursor) > 19 or not 1 <= int(raw_cursor) <= 9223372036854775807):
                return respond(
                    400,
                    {
                        "error": "커서가 올바르지 않습니다",
                        "code": "invalid_request",
                    },
                )

            limit = 50
            if raw_limit is not None:
                if not raw_limit.isdigit() or not 1 <= int(raw_limit) <= 100:
                    return respond(
                        400,
                        {
                            "error": "조회 건수는 1~100 사이여야 합니다",
                            "code": "invalid_request",
                        },
                    )
                limit = int(raw_limit)

            res = store.admin_list(status=raw_status, cursor=raw_cursor, limit=limit)
            return respond(200, res)

        # 4D. /api/v1/admin/suggestions/<id> (Admin transitions and delete)
        admin_prefix = "/api/v1/admin/suggestions/"
        match_admin_item = _ID_PATTERN.fullmatch(path[len(admin_prefix):]) if path.startswith(admin_prefix) else None
        if match_admin_item:
            if not _check_admin_auth(request_headers, headers):
                return respond(
                    401,
                    {"error": "인증이 필요합니다", "code": "unauthorized"},
                )

            identifier = path[len(admin_prefix):]

            if method == "PATCH":
                try:
                    payload = json.loads(body or b"{}")
                except (ValueError, TypeError, UnicodeDecodeError):
                    return respond(
                        400,
                        {
                            "error": "요청 값이 올바르지 않습니다",
                            "code": "invalid_request",
                        },
                    )
                if not isinstance(payload, dict):
                    return respond(
                        400,
                        {
                            "error": "요청 값이 올바르지 않습니다",
                            "code": "invalid_request",
                        },
                    )
                allowed_keys = {"status", "merged_into", "reviewer_note"}
                if not set(payload).issubset(allowed_keys) or "status" not in payload:
                    return respond(
                        400,
                        {
                            "error": "요청 값이 올바르지 않습니다",
                            "code": "invalid_request",
                        },
                    )
                target_status = payload.get("status")
                if target_status not in _ALLOWED_STATUSES:
                    return respond(
                        400,
                        {
                            "error": "상태 값이 올바르지 않습니다",
                            "code": "invalid_request",
                        },
                    )

                res = store.admin_transition(
                    identifier,
                    target_status,
                    merged_into=payload.get("merged_into"),
                    reviewer_note=payload.get("reviewer_note"),
                )
                if res is None:
                    return respond(
                        404,
                        {"error": "요청한 제안이 없습니다", "code": "not_found"},
                    )
                return respond(200, res)

            elif method == "DELETE":
                deleted = store.admin_delete(identifier)
                if not deleted:
                    return respond(
                        404,
                        {"error": "요청한 제안이 없습니다", "code": "not_found"},
                    )
                return respond(200, {"deleted": True})

            else:
                return respond(
                    405,
                    {"error": "지원하지 않는 메서드입니다", "code": "method_not_allowed"},
                )

        # 4E. Path not recognized
        return respond(
            404,
            {"error": "요청한 경로가 없습니다", "code": "not_found"},
        )

    except SuggestionDuplicateError:
        return respond(
            409,
            {
                "error": "유사한 제안이 최근에 제출되었습니다",
                "code": "duplicate_suggestion",
            },
        )
    except SuggestionLimitError:
        return respond(
            503,
            {
                "error": "제안 저장 한도에 도달했습니다",
                "code": "suggestion_limit",
            },
        )
    except (ValueError, TypeError, UnicodeDecodeError, RecursionError):
        return respond(
            400,
            {
                "error": "요청 값이 올바르지 않습니다",
                "code": "invalid_request",
            },
        )
    except (OSError, sqlite3.Error):
        return respond(
            503,
            {
                "error": "제안 저장소를 사용할 수 없습니다",
                "code": "suggestions_unavailable",
            },
        )
