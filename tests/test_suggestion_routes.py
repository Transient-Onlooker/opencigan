"""Tests for isolated suggestion API routes (ST-05)."""

import json
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import Mock, patch

from backend.http_core import make_response_headers
from backend.suggestion_routes import suggestion_api
from backend.suggestion_store import (
    CONTEXT_MAX_LENGTH,
    DESCRIPTION_MAX_LENGTH,
    GLOBAL_LIMIT,
    SUBMIT_BODY_MAX_BYTES,
    SuggestionDuplicateError,
    SuggestionLimitError,
    SuggestionStore,
    TITLE_MAX_LENGTH,
)


class SuggestionRoutesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db_path = Path(self.temp.name) / "suggestions.sqlite"
        self.store = SuggestionStore(self.db_path)
        self.admin_token = "secret-admin-token-1234567890"

    def test_cursor_larger_than_sqlite_integer_is_rejected(self):
        for path, token in (("/api/v1/suggestions", None),
                            ("/api/v1/admin/suggestions", self.admin_token)):
            status, _, _ = self._call("GET", path, query_string="cursor=9223372036854775808", token=token)
            self.assertEqual(status, 400)

    def _call(
        self,
        method,
        path,
        query_string="",
        payload=None,
        raw_body=None,
        token=None,
        client=None,
        rate_allowed=None,
        store_override=...,
        admin_token=None,
    ):
        body = (
            raw_body
            if raw_body is not None
            else (json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else b"")
        )
        request_headers = {}
        if token is not None:
            request_headers["Authorization"] = f"Bearer {token}"
        headers = make_response_headers(path, "", None)

        def default_rate_allowed(key):
            return None

        rate_fn = rate_allowed if rate_allowed is not None else default_rate_allowed
        store_fn = (lambda: self.store) if store_override is ... else store_override

        env = {}
        if admin_token is not None:
            env["OPENCIGAN_ADMIN_TOKEN"] = admin_token
        elif self.admin_token:
            env["OPENCIGAN_ADMIN_TOKEN"] = self.admin_token

        with patch.dict(os.environ, env):
            return suggestion_api(
                method=method,
                path=path,
                query_string=query_string,
                body=body,
                request_headers=request_headers,
                client=client,
                headers=headers,
                rate_allowed=rate_fn,
                suggestion_store=store_fn,
            )

    # 1. Default-off behavior
    def test_default_off_when_store_missing(self):
        status, headers, body = self._call(
            "POST",
            "/api/v1/suggestions",
            payload={"title": "제목", "description": "내용"},
            store_override=lambda: None,
        )
        self.assertEqual(status, 503)
        self.assertEqual(headers["Cache-Control"], "no-store")
        payload = json.loads(body)
        self.assertEqual(payload["code"], "suggestions_disabled")

    # 2. Public submission & initial pending status & 201 Created
    def test_submit_creates_pending_suggestion_and_returns_201_with_token(self):
        status, headers, body = self._call(
            "POST",
            "/api/v1/suggestions",
            payload={
                "title": "선생님별 시간표 인쇄",
                "description": "교사별 시간표를 일괄 인쇄하고 싶습니다.",
                "context": "학기초 교무실",
            },
        )
        self.assertEqual(status, 201)
        self.assertEqual(headers["Cache-Control"], "no-store")
        data = json.loads(body)
        self.assertIn("id", data)
        self.assertIn("token", data)
        identifier = data["id"]
        token = data["token"]

        # Check in store directly
        own = self.store.get_own(identifier, token)
        self.assertIsNotNone(own)
        self.assertEqual(own["title"], "선생님별 시간표 인쇄")
        self.assertEqual(own["status"], "pending")

        # Must not be visible in public search yet
        status, _, search_body = self._call("GET", "/api/v1/suggestions")
        self.assertEqual(status, 200)
        items = json.loads(search_body)["suggestions"]
        self.assertEqual(len(items), 0)

    # 3. Submitter self-service retrieval
    def test_author_self_service_requires_exact_bearer_token(self):
        create_res = self.store.create("다크모드", "위젯 다크모드 지원 요청")
        cid, ctoken = create_res["id"], create_res["token"]

        # No token -> 401
        status, headers, _ = self._call("GET", f"/api/v1/suggestions/{cid}")
        self.assertEqual(status, 401)
        self.assertIn("WWW-Authenticate", headers)

        # Wrong token -> 401
        status, headers, _ = self._call("GET", f"/api/v1/suggestions/{cid}", token="wrong-token-abc")
        self.assertEqual(status, 401)
        self.assertIn("WWW-Authenticate", headers)

        # Valid-shaped non-existent ID -> 401 (timing / enumeration safety)
        fake_id = "x" * 24
        status, headers, _ = self._call("GET", f"/api/v1/suggestions/{fake_id}", token=ctoken)
        self.assertEqual(status, 401)

        # Non-matching pattern path -> 404
        status, _, _ = self._call("GET", "/api/v1/suggestions/invalid_short_id", token=ctoken)
        self.assertEqual(status, 404)

        # Correct token -> 200
        status, headers, body = self._call("GET", f"/api/v1/suggestions/{cid}", token=ctoken)
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertEqual(data["id"], cid)
        self.assertEqual(data["title"], "다크모드")
        self.assertEqual(data["status"], "pending")
        self.assertNotIn("token_hash", data)

    # 4. Approved-only public search
    def test_public_search_returns_only_approved_items(self):
        r1 = self.store.create("승인된 제안 1", "내용 1")
        r2 = self.store.create("대기 중 제안 2", "내용 2")
        r3 = self.store.create("반려된 제안 3", "내용 3")

        self.store.admin_transition(r1["id"], "approved")
        self.store.admin_transition(r3["id"], "rejected")

        status, _, body = self._call("GET", "/api/v1/suggestions")
        self.assertEqual(status, 200)
        items = json.loads(body)["suggestions"]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["id"], r1["id"])
        self.assertEqual(items[0]["title"], "승인된 제안 1")

        # Keyword search
        status, _, body = self._call("GET", "/api/v1/suggestions", query_string="q=제안")
        self.assertEqual(status, 200)
        self.assertEqual(len(json.loads(body)["suggestions"]), 1)

        status, _, body = self._call("GET", "/api/v1/suggestions", query_string="q=대기")
        self.assertEqual(status, 200)
        self.assertEqual(len(json.loads(body)["suggestions"]), 0)

    # 5. Admin bearer authorization and minimum entropy checks
    def test_admin_endpoints_require_admin_bearer_token_and_minimum_entropy(self):
        # Missing token
        status, headers, _ = self._call("GET", "/api/v1/admin/suggestions", token=None)
        self.assertEqual(status, 401)
        self.assertIn("WWW-Authenticate", headers)

        # Invalid token
        status, headers, _ = self._call("GET", "/api/v1/admin/suggestions", token="wrong-secret-token")
        self.assertEqual(status, 401)

        # Weak admin token in environment (< 16 chars) rejected even with matching bearer token
        status, headers, _ = self._call(
            "GET",
            "/api/v1/admin/suggestions",
            token="short",
            admin_token="short",
        )
        self.assertEqual(status, 401)
        self.assertIn("WWW-Authenticate", headers)

        # Valid admin token (>= 16 chars)
        status, _, body = self._call("GET", "/api/v1/admin/suggestions", token=self.admin_token)
        self.assertEqual(status, 200)
        self.assertIn("suggestions", json.loads(body))

    # 6. Admin transitions and graph enforcement
    def test_admin_transitions_and_graph_enforcement(self):
        r1 = self.store.create("기능 제안", "설명입니다")
        r2 = self.store.create("타겟 제안", "병합 대상입니다")
        aid, tid = r1["id"], r2["id"]

        # Transition pending -> approved
        status, _, body = self._call(
            "PATCH",
            f"/api/v1/admin/suggestions/{aid}",
            payload={"status": "approved", "reviewer_note": "검토 승인"},
            token=self.admin_token,
        )
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertEqual(data["status"], "approved")
        self.assertEqual(data["reviewer_note"], "검토 승인")

        # Transition approved -> approved is illegal in store graph -> 400
        status, _, body = self._call(
            "PATCH",
            f"/api/v1/admin/suggestions/{aid}",
            payload={"status": "approved"},
            token=self.admin_token,
        )
        self.assertEqual(status, 400)
        self.assertEqual(json.loads(body)["code"], "invalid_request")

        # Transition approved -> rejected
        status, _, body = self._call(
            "PATCH",
            f"/api/v1/admin/suggestions/{aid}",
            payload={"status": "rejected"},
            token=self.admin_token,
        )
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["status"], "rejected")

        # Merge transition
        r3 = self.store.create("중복 제안", "중복 내용")
        dup_id = r3["id"]
        status, _, body = self._call(
            "PATCH",
            f"/api/v1/admin/suggestions/{dup_id}",
            payload={"status": "merged", "merged_into": tid},
            token=self.admin_token,
        )
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["status"], "merged")
        self.assertEqual(json.loads(body)["merged_into"], tid)

    # 7. Admin deletion
    def test_admin_delete_endpoints_and_integrity(self):
        r1 = self.store.create("삭제 제안", "삭제할 내용")
        r2 = self.store.create("병합 중복", "중복 내용")
        aid, bid = r1["id"], r2["id"]
        self.store.admin_transition(bid, "merged", merged_into=aid)

        # Cannot delete aid because bid is merged into it -> 400
        status, _, body = self._call("DELETE", f"/api/v1/admin/suggestions/{aid}", token=self.admin_token)
        self.assertEqual(status, 400)
        self.assertEqual(json.loads(body)["code"], "invalid_request")

        # Delete bid first
        status, _, body = self._call("DELETE", f"/api/v1/admin/suggestions/{bid}", token=self.admin_token)
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(body)["deleted"])

        # Now delete aid succeeds
        status, _, body = self._call("DELETE", f"/api/v1/admin/suggestions/{aid}", token=self.admin_token)
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(body)["deleted"])

        # Deleting non-existent -> 404
        status, _, body = self._call("DELETE", f"/api/v1/admin/suggestions/{aid}", token=self.admin_token)
        self.assertEqual(status, 404)

    # 8. Request bounds, input validation & errors
    def test_body_size_bound_413(self):
        large_body = b"x" * (SUBMIT_BODY_MAX_BYTES + 1)
        status, _, body = self._call(
            "POST",
            "/api/v1/suggestions",
            raw_body=large_body,
        )
        self.assertEqual(status, 413)
        self.assertEqual(json.loads(body)["code"], "payload_too_large")

    def test_input_validation_empty_or_excessive(self):
        # Empty title
        status, _, body = self._call("POST", "/api/v1/suggestions", payload={"title": "", "description": "내용"})
        self.assertEqual(status, 400)
        self.assertEqual(json.loads(body)["code"], "invalid_request")

        # Exceeding TITLE_MAX_LENGTH
        status, _, body = self._call("POST", "/api/v1/suggestions", payload={"title": "A" * (TITLE_MAX_LENGTH + 1), "description": "내용"})
        self.assertEqual(status, 400)

        # Exceeding DESCRIPTION_MAX_LENGTH
        status, _, body = self._call("POST", "/api/v1/suggestions", payload={"title": "제목", "description": "B" * (DESCRIPTION_MAX_LENGTH + 1)})
        self.assertEqual(status, 400)

        # Exceeding CONTEXT_MAX_LENGTH
        status, _, body = self._call("POST", "/api/v1/suggestions", payload={"title": "제목", "description": "내용", "context": "C" * (CONTEXT_MAX_LENGTH + 1)})
        self.assertEqual(status, 400)

        # Unknown field injection
        status, _, body = self._call("POST", "/api/v1/suggestions", payload={"title": "제목", "description": "내용", "status": "approved"})
        self.assertEqual(status, 400)

    def test_query_bounds_and_invalid_cursor(self):
        # Limit > 100
        status, _, _ = self._call("GET", "/api/v1/suggestions", query_string="limit=101")
        self.assertEqual(status, 400)

        # Negative or non-numeric cursor
        status, _, _ = self._call("GET", "/api/v1/suggestions", query_string="cursor=-5")
        self.assertEqual(status, 400)

        status, _, _ = self._call("GET", "/api/v1/suggestions", query_string="cursor=abc")
        self.assertEqual(status, 400)

        # Search query > 100 chars
        status, _, _ = self._call("GET", "/api/v1/suggestions", query_string=f"q={'q' * 101}")
        self.assertEqual(status, 400)

        # Disallowed query param
        status, _, _ = self._call("GET", "/api/v1/suggestions", query_string="status=approved")
        self.assertEqual(status, 400)

    # 9. Duplicate submission returns 409
    def test_duplicate_submission_returns_409(self):
        payload = {"title": "중복 방지 제목", "description": "동일 내용 설명"}
        status, _, _ = self._call("POST", "/api/v1/suggestions", payload=payload)
        self.assertEqual(status, 201)

        # Immediate duplicate
        status, _, body = self._call("POST", "/api/v1/suggestions", payload=payload)
        self.assertEqual(status, 409)
        self.assertEqual(json.loads(body)["code"], "duplicate_suggestion")

    # 10. Rate limiting returns 429 with Retry-After
    def test_rate_limiting_returns_429(self):
        def mock_rate(key):
            self.assertEqual(key, ("suggestions", "client-1.2.3.4"))
            return 45

        status, headers, body = self._call(
            "POST",
            "/api/v1/suggestions",
            payload={"title": "제목", "description": "내용"},
            client="client-1.2.3.4",
            rate_allowed=mock_rate,
        )
        self.assertEqual(status, 429)
        self.assertEqual(headers["Retry-After"], "45")
        self.assertEqual(json.loads(body)["code"], "rate_limited")

    # 11. Storage limits return 503
    def test_storage_limit_returns_503(self):
        mock_store = Mock()
        mock_store.create.side_effect = SuggestionLimitError("Suggestion limit reached")

        status, _, body = self._call(
            "POST",
            "/api/v1/suggestions",
            payload={"title": "제목", "description": "내용"},
            store_override=lambda: mock_store,
        )
        self.assertEqual(status, 503)
        self.assertEqual(json.loads(body)["code"], "suggestion_limit")

    # 12. Token and IP privacy (No token in logs or error bodies, no IP in DB)
    def test_privacy_no_ip_and_token_out_of_logs_and_errors(self):
        status, _, body = self._call(
            "POST",
            "/api/v1/suggestions",
            payload={"title": "프라이버시", "description": "IP 저장 금지"},
            client="198.51.100.25",
        )
        self.assertEqual(status, 201)
        created = json.loads(body)
        token = created["token"]

        # Check DB directly to ensure no IP is recorded anywhere in suggestions schema
        with closing(sqlite3.connect(self.db_path)) as db:
            cols = [col[1] for col in db.execute("PRAGMA table_info(suggestions)").fetchall()]
            self.assertNotIn("ip", cols)
            self.assertNotIn("client_ip", cols)
            self.assertNotIn("ip_hash", cols)

            row = db.execute("SELECT * FROM suggestions WHERE id=?", (created["id"],)).fetchone()
            row_str = " ".join(str(val) for val in row)
            self.assertNotIn("198.51.100.25", row_str)
            self.assertNotIn(token, row_str)

        # Test error response when bad auth supplied doesn't echo token
        secret_token = "secret-token-do-not-leak"
        status, _, err_body = self._call("GET", f"/api/v1/suggestions/{created['id']}", token=secret_token)
        self.assertEqual(status, 401)
        self.assertNotIn(secret_token.encode("utf-8"), err_body)

    # 13. Method not allowed (405)
    def test_method_not_allowed(self):
        for method in ("PUT", "DELETE"):
            status, _, body = self._call(method, "/api/v1/suggestions")
            self.assertEqual(status, 405)
            self.assertEqual(json.loads(body)["code"], "method_not_allowed")

        status, _, body = self._call("POST", f"/api/v1/suggestions/{'a'*24}")
        self.assertEqual(status, 405)


if __name__ == "__main__":
    unittest.main()
