"""Anonymous feature-suggestion storage (ST-05).

Isolated SQLite database for accepting, reviewing, and searching
feature suggestions without user accounts.  The store is inactive
when OPENCIGAN_SUGGESTION_DB is unset.  Route wiring is handled
separately; this module only provides the data layer.
"""

import hashlib
import json
import os
import re
import secrets
import sqlite3
import time
from contextlib import closing
from datetime import datetime, timedelta, timezone

TITLE_MAX_LENGTH = 100
DESCRIPTION_MAX_LENGTH = 2000
CONTEXT_MAX_LENGTH = 500
GLOBAL_LIMIT = 2000
SUBMIT_BODY_MAX_BYTES = 4096

VALID_STATUSES = ("pending", "approved", "rejected", "merged")
ADMIN_TRANSITIONS = {
    "pending":  ("approved", "rejected", "merged"),
    "approved": ("rejected",),
    "rejected": ("approved",),
    "merged":   ("pending",),
}

_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

KST = timezone(timedelta(hours=9))


class SuggestionLimitError(Exception):
    """Raised when the global suggestion cap is reached."""


class SuggestionDuplicateError(Exception):
    """Raised when a duplicate submission is detected within the window."""


def _sanitize_text(value, max_length, field_name):
    """Validate and clean a user-supplied text field."""
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    stripped = value.strip()
    if not stripped:
        raise ValueError(f"{field_name} is required")
    if len(stripped) > max_length:
        raise ValueError(
            f"{field_name} must be {max_length} characters or fewer"
        )
    cleaned = _CONTROL_CHARS.sub("", stripped)
    if not cleaned.strip():
        raise ValueError(f"{field_name} is required")
    return cleaned


def _sanitize_optional_text(value, max_length, field_name):
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    return _sanitize_text(value, max_length, field_name)


def _escape_like(text):
    """Escape SQL LIKE special wildcards %, _ and escape char /."""
    return text.replace("/", "//").replace("%", "/%").replace("_", "/_")


def _fingerprint(title, description):
    """Content-based deduplication fingerprint.

    Fields are JSON-serialised separately to preserve the boundary
    between title and description before hashing.
    """
    payload = json.dumps(
        [title.casefold().split(), description.casefold().split()],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class SuggestionStore:
    """Persistent suggestion storage backed by an isolated SQLite database."""

    DEDUP_WINDOW_SECONDS = 3600

    def __init__(self, path):
        self.path = str(path)
        if self.path == ":memory:":
            raise ValueError(
                "suggestion store requires a persistent database; "
                "use a temporary file for tests"
            )
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            pass
        else:
            os.close(fd)
        with closing(self._connect()) as db:
            self._init_schema(db)

    @staticmethod
    def _init_schema(db):
        db.executescript(
            "CREATE TABLE IF NOT EXISTS suggestions ("
            "  id            TEXT PRIMARY KEY,"
            "  token_hash    TEXT NOT NULL,"
            "  title         TEXT NOT NULL,"
            "  description   TEXT NOT NULL,"
            "  context       TEXT,"
            "  status        TEXT NOT NULL DEFAULT 'pending',"
            "  fingerprint   TEXT NOT NULL,"
            "  merged_into   TEXT REFERENCES suggestions(id),"
            "  created_at    TEXT NOT NULL,"
            "  reviewed_at   TEXT,"
            "  reviewer_note TEXT"
            ");"
            "CREATE INDEX IF NOT EXISTS idx_suggestions_status"
            "  ON suggestions(status);"
            "CREATE INDEX IF NOT EXISTS idx_suggestions_fingerprint"
            "  ON suggestions(fingerprint, created_at);"
            "CREATE INDEX IF NOT EXISTS idx_suggestions_created"
            "  ON suggestions(created_at);"
            "CREATE INDEX IF NOT EXISTS idx_suggestions_merged_into"
            "  ON suggestions(merged_into);"
        )

    def _connect(self):
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=10000")
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA foreign_keys=ON")
        return db

    # -- Token hashing (mirrors webhook_store) -------------------------

    @staticmethod
    def _token_hash(token):
        if (not isinstance(token, str)
                or not re.fullmatch(r"[A-Za-z0-9_-]{43}", token)):
            return ""
        return hashlib.sha256(token.encode("ascii")).hexdigest()

    # -- Anonymous submission ------------------------------------------

    def create(self, title, description, context=None, *, now=None):
        """Accept a new suggestion and return {id, token}.

        Raises SuggestionDuplicateError if the same content fingerprint
        was submitted within the deduplication window.
        Raises SuggestionLimitError when the global cap is reached.
        """
        clean_title = _sanitize_text(title, TITLE_MAX_LENGTH, "title")
        clean_desc = _sanitize_text(
            description, DESCRIPTION_MAX_LENGTH, "description"
        )
        clean_ctx = _sanitize_optional_text(
            context, CONTEXT_MAX_LENGTH, "context"
        )

        fp = _fingerprint(clean_title, clean_desc)
        identifier = secrets.token_urlsafe(18)
        token = secrets.token_urlsafe(32)
        ts = now if now is not None else time.time()
        created_at = datetime.fromtimestamp(ts, tz=KST).isoformat()
        dedup_cutoff = datetime.fromtimestamp(
            ts - self.DEDUP_WINDOW_SECONDS, tz=KST,
        ).isoformat()

        with closing(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                total = db.execute(
                    "SELECT COUNT(*) FROM suggestions"
                ).fetchone()[0]
                if total >= GLOBAL_LIMIT:
                    raise SuggestionLimitError("Suggestion limit reached")

                dup = db.execute(
                    "SELECT id FROM suggestions "
                    "WHERE fingerprint=? AND created_at>=?",
                    (fp, dedup_cutoff),
                ).fetchone()
                if dup:
                    raise SuggestionDuplicateError(
                        "A similar suggestion was recently submitted"
                    )

                db.execute(
                    "INSERT INTO suggestions"
                    "(id, token_hash, title, description, context,"
                    " fingerprint, created_at)"
                    " VALUES (?,?,?,?,?,?,?)",
                    (identifier, self._token_hash(token), clean_title,
                     clean_desc, clean_ctx, fp, created_at),
                )
                db.execute("COMMIT")
            except BaseException:
                db.execute("ROLLBACK")
                raise

        return {"id": identifier, "token": token}

    # -- Submitter self-service (requires own token) -------------------

    def get_own(self, identifier, token):
        """Return a suggestion visible to its author, or None."""
        with closing(self._connect()) as db:
            row = db.execute(
                "SELECT id, title, description, context, status,"
                " created_at, reviewed_at, merged_into"
                " FROM suggestions WHERE id=? AND token_hash=?",
                (identifier, self._token_hash(token)),
            ).fetchone()
        return dict(row) if row else None

    # -- Approved-only public search (unauthenticated) -----------------

    def search_approved(self, query=None, cursor=None, limit=20):
        """Return approved suggestions, optionally filtered by keyword."""
        if not isinstance(limit, int) or limit < 1 or limit > 100:
            raise ValueError("limit must be 1-100")
        if cursor is not None:
            if not isinstance(cursor, str) or not cursor.isdigit():
                raise ValueError("invalid cursor")

        with closing(self._connect()) as db:
            conditions = ["status='approved'"]
            params = []
            if query and isinstance(query, str) and query.strip():
                keyword = "%" + _escape_like(query.strip()[:100]) + "%"
                conditions.append(
                    "(title LIKE ? ESCAPE '/' OR description LIKE ? ESCAPE '/')"
                )
                params.extend([keyword, keyword])
            if cursor:
                conditions.append("rowid<?")
                params.append(int(cursor))
            where = "WHERE " + " AND ".join(conditions)
            params.append(limit + 1)
            rows = db.execute(
                "SELECT rowid, id, title, description, context, created_at"
                " FROM suggestions " + where
                + " ORDER BY rowid DESC LIMIT ?",
                params,
            ).fetchall()

        has_more = len(rows) > limit
        rows = rows[:limit]
        items = [
            {"id": r["id"], "title": r["title"],
             "description": r["description"], "context": r["context"],
             "createdAt": r["created_at"]}
            for r in rows
        ]
        next_cursor = str(rows[-1]["rowid"]) if has_more and rows else None
        return {"suggestions": items, "nextCursor": next_cursor}

    # -- Admin: full listing, transitions, and deletion ----------------

    def admin_list(self, status=None, cursor=None, limit=50):
        """List suggestions for admin review."""
        if status is not None and status not in VALID_STATUSES:
            raise ValueError("invalid status filter")
        if not isinstance(limit, int) or limit < 1 or limit > 100:
            raise ValueError("limit must be 1-100")
        if cursor is not None:
            if not isinstance(cursor, str) or not cursor.isdigit():
                raise ValueError("invalid cursor")

        with closing(self._connect()) as db:
            conditions = []
            params = []
            if status:
                conditions.append("status=?")
                params.append(status)
            if cursor:
                conditions.append("rowid<?")
                params.append(int(cursor))
            where = (
                ("WHERE " + " AND ".join(conditions)) if conditions else ""
            )
            params.append(limit + 1)
            rows = db.execute(
                "SELECT rowid, id, title, description, context, status,"
                " created_at, reviewed_at, merged_into, reviewer_note"
                " FROM suggestions " + where
                + " ORDER BY rowid DESC LIMIT ?",
                params,
            ).fetchall()

        has_more = len(rows) > limit
        rows = rows[:limit]
        items = [dict(r) for r in rows]
        for item in items:
            item.pop("rowid", None)
        next_cursor = (
            str(rows[-1]["rowid"]) if has_more and rows else None
        )
        return {"suggestions": items, "nextCursor": next_cursor}

    def admin_transition(self, identifier, new_status, *,
                         merged_into=None, reviewer_note=None, now=None):
        """Move a suggestion to new_status following the allowed graph.

        Returns the updated row dict on success, None if not found,
        and raises ValueError on illegal transitions.
        """
        if new_status not in VALID_STATUSES:
            raise ValueError(f"invalid target status: {new_status}")

        reviewed_at = datetime.fromtimestamp(
            now if now is not None else time.time(), tz=KST,
        ).isoformat()

        with closing(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                row = db.execute(
                    "SELECT id, status FROM suggestions WHERE id=?",
                    (identifier,),
                ).fetchone()
                if not row:
                    db.execute("COMMIT")
                    return None

                current = row["status"]
                allowed = ADMIN_TRANSITIONS.get(current, ())
                if new_status not in allowed:
                    raise ValueError(
                        f"cannot transition from {current} to {new_status}"
                    )

                if new_status == "merged":
                    if (not merged_into
                            or not isinstance(merged_into, str)):
                        raise ValueError(
                            "merged_into is required for merge"
                        )
                    target = db.execute(
                        "SELECT id, status, merged_into FROM suggestions WHERE id=?",
                        (merged_into,),
                    ).fetchone()
                    if not target:
                        raise ValueError("merge target does not exist")
                    if merged_into == identifier:
                        raise ValueError("cannot merge into self")
                    if target["status"] == "merged":
                        raise ValueError(
                            "cannot merge into an already merged suggestion"
                        )
                    if target["status"] == "rejected":
                        raise ValueError(
                            "cannot merge into a rejected suggestion"
                        )

                    curr = target["merged_into"]
                    seen = {identifier, merged_into}
                    while curr:
                        if curr == identifier:
                            raise ValueError("merge cycle detected")
                        if curr in seen:
                            break
                        seen.add(curr)
                        curr_row = db.execute(
                            "SELECT merged_into FROM suggestions WHERE id=?",
                            (curr,),
                        ).fetchone()
                        curr = curr_row["merged_into"] if curr_row else None

                clean_note = _sanitize_optional_text(
                    reviewer_note, CONTEXT_MAX_LENGTH, "reviewer_note"
                )

                db.execute(
                    "UPDATE suggestions SET status=?, reviewed_at=?,"
                    " merged_into=?, reviewer_note=? WHERE id=?",
                    (new_status, reviewed_at,
                     merged_into if new_status == "merged" else None,
                     clean_note, identifier),
                )
                db.execute("COMMIT")
            except BaseException:
                db.execute("ROLLBACK")
                raise

        with closing(self._connect()) as db:
            result = db.execute(
                "SELECT id, title, description, context, status,"
                " created_at, reviewed_at, merged_into, reviewer_note"
                " FROM suggestions WHERE id=?",
                (identifier,),
            ).fetchone()
        return dict(result) if result else None

    def admin_delete(self, identifier):
        """Delete a suggestion by identifier.

        Returns True on success, False if the suggestion was not found.
        Raises ValueError if other suggestions are currently merged into this
        suggestion, preserving merge target referential integrity.
        """
        if not isinstance(identifier, str) or not identifier.strip():
            raise ValueError("identifier is required")

        with closing(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                exists = db.execute(
                    "SELECT id FROM suggestions WHERE id=?",
                    (identifier,),
                ).fetchone()
                if not exists:
                    db.execute("COMMIT")
                    return False

                merged_count = db.execute(
                    "SELECT COUNT(*) FROM suggestions WHERE merged_into=?",
                    (identifier,),
                ).fetchone()[0]
                if merged_count > 0:
                    raise ValueError(
                        f"cannot delete suggestion: {merged_count} suggestion(s)"
                        " are merged into it"
                    )

                cursor = db.execute(
                    "DELETE FROM suggestions WHERE id=?",
                    (identifier,),
                )
                db.execute("COMMIT")
                return cursor.rowcount == 1
            except BaseException:
                db.execute("ROLLBACK")
                raise
