import os
import re
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path

from backend.suggestion_store import (
    ADMIN_TRANSITIONS,
    GLOBAL_LIMIT,
    SuggestionDuplicateError,
    SuggestionLimitError,
    SuggestionStore,
    TITLE_MAX_LENGTH,
    DESCRIPTION_MAX_LENGTH,
    CONTEXT_MAX_LENGTH,
)


class SuggestionStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "suggestions.sqlite"
        self.store = SuggestionStore(self.path)

    def test_persistent_database_required(self):
        with self.assertRaises(ValueError):
            SuggestionStore(":memory:")

    def test_sqlite_backup_preserves_private_and_approved_state(self):
        pending = self.store.create("대기 중", "비공개 제안")
        approved = self.store.create("승인됨", "공개 제안")
        self.store.admin_transition(approved["id"], "approved")
        backup = Path(self.temp.name) / "backup.sqlite"
        with closing(sqlite3.connect(self.path)) as source, closing(sqlite3.connect(backup)) as target:
            source.backup(target)
        restored = SuggestionStore(backup)
        self.assertEqual(restored.get_own(pending["id"], pending["token"])["status"], "pending")
        self.assertEqual([item["id"] for item in restored.search_approved()["suggestions"]], [approved["id"]])

    def test_create_returns_opaque_token_and_hashes_in_db_no_ip_stored(self):
        res = self.store.create(
            "선생님별 시간표 인쇄 기능",
            "교사별 주간 시간표를 한 번에 PDF로 내보내고 싶습니다.",
            "교무실에서 학기 초 출력 시 사용",
            now=1700000000,
        )
        identifier, token = res["id"], res["token"]
        self.assertTrue(re.fullmatch(r"[A-Za-z0-9_-]{24}", identifier))
        self.assertTrue(re.fullmatch(r"[A-Za-z0-9_-]{43}", token))

        with closing(sqlite3.connect(self.path)) as db:
            columns = [c[1] for c in db.execute("PRAGMA table_info(suggestions)").fetchall()]
            self.assertNotIn("ip_hash", columns)
            self.assertNotIn("client_ip", columns)

            row = db.execute(
                "SELECT token_hash, status FROM suggestions WHERE id=?",
                (identifier,),
            ).fetchone()
        token_hash, status = row
        self.assertNotEqual(token_hash, token)
        self.assertEqual(len(token_hash), 64)
        self.assertEqual(status, "pending")

    def test_get_own_requires_exact_token(self):
        res = self.store.create("위젯 다크모드", "배경색 자동 반전 요청")
        identifier, token = res["id"], res["token"]

        self.assertIsNone(self.store.get_own(identifier, "wrong_token"))
        self.assertIsNone(self.store.get_own("nonexistent_id", token))

        own = self.store.get_own(identifier, token)
        self.assertIsNotNone(own)
        self.assertEqual(own["title"], "위젯 다크모드")
        self.assertEqual(own["status"], "pending")
        self.assertNotIn("token_hash", own)
        self.assertNotIn("ip_hash", own)

    def test_plain_text_preserved_and_control_characters_stripped(self):
        res = self.store.create(
            "<script>alert('xss')</script> 급식 & 시간표 < 1교시 >",
            '<b>굵게</b> 및 \'따옴표\' & "쌍따옴표" 포함\x00\x08설명',
            "<iframe src='evil.com'></iframe> 사용 상황\x1f",
        )
        own = self.store.get_own(res["id"], res["token"])
        self.assertEqual(
            own["title"],
            "<script>alert('xss')</script> 급식 & 시간표 < 1교시 >",
        )
        self.assertEqual(
            own["description"],
            '<b>굵게</b> 및 \'따옴표\' & "쌍따옴표" 포함설명',
        )
        self.assertEqual(
            own["context"],
            "<iframe src='evil.com'></iframe> 사용 상황",
        )
        self.assertNotIn("\x00", own["description"])
        self.assertNotIn("\x08", own["description"])
        self.assertNotIn("\x1f", own["context"])

    def test_input_length_and_empty_boundaries(self):
        with self.assertRaises(ValueError):
            self.store.create("", "설명")
        with self.assertRaises(ValueError):
            self.store.create("   ", "설명")
        with self.assertRaises(ValueError):
            self.store.create("제목", "")
        with self.assertRaises(ValueError):
            self.store.create("A" * (TITLE_MAX_LENGTH + 1), "설명")
        with self.assertRaises(ValueError):
            self.store.create("제목", "B" * (DESCRIPTION_MAX_LENGTH + 1))
        with self.assertRaises(ValueError):
            self.store.create("제목", "설명", "C" * (CONTEXT_MAX_LENGTH + 1))

    def test_duplicate_submission_blocked_within_window(self):
        t0 = 1700000000
        self.store.create("동일 제목", "동일 내용 설명", now=t0)

        with self.assertRaises(SuggestionDuplicateError):
            self.store.create("동일 제목", "동일 내용 설명", now=t0 + 60)

        with self.assertRaises(SuggestionDuplicateError):
            self.store.create("  동일   제목  ", " 동일 내용   설명 ", now=t0 + 120)

        later = self.store.create("동일 제목", "동일 내용 설명", now=t0 + 3601)
        self.assertIsNotNone(later["id"])

    def test_concurrent_duplicate_submission_atomic_rejection(self):
        def submit(idx):
            try:
                return self.store.create("동시 제목", "동시 내용", now=1700000000)
            except SuggestionDuplicateError:
                return None

        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(submit, range(4)))

        successes = [r for r in results if r is not None]
        self.assertEqual(len(successes), 1)

    def test_search_approved_only_returns_approved_items(self):
        res1 = self.store.create("승인 대상", "시간표 비교 화면")
        res2 = self.store.create("대기 항목", "미승인 제안")
        res3 = self.store.create("반려 항목", "적합하지 않음")

        self.store.admin_transition(res1["id"], "approved")
        self.store.admin_transition(res3["id"], "rejected")

        search_all = self.store.search_approved()
        titles = [item["title"] for item in search_all["suggestions"]]
        self.assertIn("승인 대상", titles)
        self.assertNotIn("대기 항목", titles)
        self.assertNotIn("반려 항목", titles)

        search_kw = self.store.search_approved(query="시간표")
        self.assertEqual(len(search_kw["suggestions"]), 1)
        self.assertEqual(search_kw["suggestions"][0]["id"], res1["id"])

        search_miss = self.store.search_approved(query="존재하지않음")
        self.assertEqual(len(search_miss["suggestions"]), 0)

    def test_search_approved_like_wildcard_escaping(self):
        res_pct = self.store.create("100% 만족 기능", "정확한 백분율 검색")
        res_under = self.store.create("a_b 변수 표기", "언더스코어 검색")
        res_slash = self.store.create("A/B 테스트", "슬래시 검색")
        res_normal = self.store.create("100 percent 일반", "일반 단어")
        res_other = self.store.create("axb 일반", "axb 단어")

        for r in (res_pct, res_under, res_slash, res_normal, res_other):
            self.store.admin_transition(r["id"], "approved")

        # '%' should match exact '100% 만족 기능', not '100 percent 일반' or 'axb 일반'
        search_pct = self.store.search_approved(query="%")
        self.assertEqual(len(search_pct["suggestions"]), 1)
        self.assertEqual(search_pct["suggestions"][0]["id"], res_pct["id"])

        # '_' should match exact 'a_b 변수 표기', not 'axb 일반'
        search_under = self.store.search_approved(query="_")
        self.assertEqual(len(search_under["suggestions"]), 1)
        self.assertEqual(search_under["suggestions"][0]["id"], res_under["id"])

        # '/' escape char itself
        search_slash = self.store.search_approved(query="/")
        self.assertEqual(len(search_slash["suggestions"]), 1)
        self.assertEqual(search_slash["suggestions"][0]["id"], res_slash["id"])

    def test_admin_state_transitions_and_graph_enforcement(self):
        res1 = self.store.create("기능 A", "설명 A")
        res2 = self.store.create("기능 B (원본)", "설명 B")
        aid, bid = res1["id"], res2["id"]

        with self.assertRaises(ValueError):
            self.store.admin_transition(aid, "invalid_status")

        approved = self.store.admin_transition(aid, "approved", reviewer_note="좋은 제안")
        self.assertEqual(approved["status"], "approved")
        self.assertEqual(approved["reviewer_note"], "좋은 제안")
        self.assertIsNotNone(approved["reviewed_at"])

        with self.assertRaises(ValueError):
            self.store.admin_transition(aid, "approved")

        rejected = self.store.admin_transition(aid, "rejected", reviewer_note="정책상 보류")
        self.assertEqual(rejected["status"], "rejected")

        re_approved = self.store.admin_transition(aid, "approved")
        self.assertEqual(re_approved["status"], "approved")

        res_dup = self.store.create("기능 C (중복)", "설명 C")
        cid = res_dup["id"]

        with self.assertRaises(ValueError):
            self.store.admin_transition(cid, "merged")
        with self.assertRaises(ValueError):
            self.store.admin_transition(cid, "merged", merged_into=cid)
        with self.assertRaises(ValueError):
            self.store.admin_transition(cid, "merged", merged_into="missing_id")

        merged = self.store.admin_transition(cid, "merged", merged_into=bid)
        self.assertEqual(merged["status"], "merged")
        self.assertEqual(merged["merged_into"], bid)

        with self.assertRaises(ValueError):
            self.store.admin_transition(cid, "approved")

        # Unmerge back to pending
        unmerged = self.store.admin_transition(cid, "pending")
        self.assertEqual(unmerged["status"], "pending")
        self.assertIsNone(unmerged["merged_into"])

    def test_merge_cycle_and_chain_prevention(self):
        r1 = self.store.create("대상 1", "내용 1")["id"]
        r2 = self.store.create("대상 2", "내용 2")["id"]
        r3 = self.store.create("대상 3", "내용 3")["id"]

        # Merge r2 into r1
        self.store.admin_transition(r2, "merged", merged_into=r1)

        # Cannot merge into already merged item (r2)
        with self.assertRaises(ValueError) as ctx:
            self.store.admin_transition(r3, "merged", merged_into=r2)
        self.assertIn("already merged", str(ctx.exception))

        # Cannot merge into rejected item
        r_rej = self.store.create("반려 제안", "내용")["id"]
        self.store.admin_transition(r_rej, "rejected")
        with self.assertRaises(ValueError) as ctx:
            self.store.admin_transition(r3, "merged", merged_into=r_rej)
        self.assertIn("rejected", str(ctx.exception))

        # Cycle prevention: r1 cannot merge into r2 (r2 is merged into r1)
        with self.assertRaises(ValueError) as ctx:
            self.store.admin_transition(r1, "merged", merged_into=r2)
        # r2 is already merged, so caught by either check
        self.assertTrue("already merged" in str(ctx.exception) or "merge cycle" in str(ctx.exception))

    def test_admin_list_and_status_filtering(self):
        r1 = self.store.create("제안 1", "내용 1")
        r2 = self.store.create("제안 2", "내용 2")
        self.store.admin_transition(r1["id"], "approved")

        all_items = self.store.admin_list()
        self.assertEqual(len(all_items["suggestions"]), 2)

        approved_only = self.store.admin_list(status="approved")
        self.assertEqual(len(approved_only["suggestions"]), 1)
        self.assertEqual(approved_only["suggestions"][0]["id"], r1["id"])

        pending_only = self.store.admin_list(status="pending")
        self.assertEqual(len(pending_only["suggestions"]), 1)
        self.assertEqual(pending_only["suggestions"][0]["id"], r2["id"])

    def test_admin_delete_removes_unreferenced_suggestion(self):
        r1 = self.store.create("삭제 대상 제안", "삭제되어야 하는 설명")
        identifier = r1["id"]

        self.assertTrue(self.store.admin_delete(identifier))
        self.assertIsNone(self.store.get_own(identifier, r1["token"]))
        self.assertFalse(self.store.admin_delete(identifier))
        self.assertFalse(self.store.admin_delete("nonexistent_id"))

    def test_admin_delete_blocked_when_other_suggestions_merged_into_it(self):
        target = self.store.create("메인 제안", "원본 기능 요청")
        duplicate = self.store.create("중복 제안", "유사한 기능 요청")
        target_id, dup_id = target["id"], duplicate["id"]

        self.store.admin_transition(dup_id, "merged", merged_into=target_id)

        with self.assertRaises(ValueError) as ctx:
            self.store.admin_delete(target_id)
        self.assertIn("merged into it", str(ctx.exception))

        with closing(sqlite3.connect(self.path)) as db:
            row = db.execute("SELECT id FROM suggestions WHERE id=?", (target_id,)).fetchone()
            self.assertIsNotNone(row)

        self.assertTrue(self.store.admin_delete(dup_id))
        self.assertTrue(self.store.admin_delete(target_id))


if __name__ == "__main__":
    unittest.main()
