"""Opt-in SQLite persistence for subscription schedules and due queue entries."""

import hashlib
import json
import math
import re
import sqlite3
import time
from contextlib import closing
from datetime import date, timedelta
from pathlib import Path

from backend.scheduled_lessons import scheduled_event_id
from backend.webhook_store import MAX_PENDING_PER_SUBSCRIPTION


_MODES = {"immediate", "daily_summary", "subject_prep"}
_TIME_RE = re.compile(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]\Z")
_TOKEN_RE = re.compile(r"[A-Za-z0-9_-]{43}\Z")


class ScheduledStore:
    """Schedule persistence. Construction is inert; methods operate on an existing DB."""

    def __init__(self, path):
        self.path = str(path)

    def _connect(self):
        db = sqlite3.connect(Path(self.path).absolute().as_uri() + "?mode=rw", uri=True, timeout=10, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        return db

    @staticmethod
    def _token_hash(token):
        if not isinstance(token, str) or not _TOKEN_RE.fullmatch(token):
            return ""
        return hashlib.sha256(token.encode("ascii")).hexdigest()

    @staticmethod
    def _validate_schedule(mode, time_kst, subject):
        if not isinstance(mode, str) or mode not in _MODES or not isinstance(time_kst, str) or not _TIME_RE.fullmatch(time_kst):
            raise ValueError("invalid schedule")
        if mode == "subject_prep":
            if not isinstance(subject, str) or not subject.strip() or len(subject) > 50:
                raise ValueError("invalid subject")
            return subject.strip()
        if subject is not None:
            raise ValueError("subject is only valid for subject_prep")
        return None

    @staticmethod
    def _ensure_schema(db):
        db.execute("""
            CREATE TABLE IF NOT EXISTS scheduled_settings (
                subscription_id TEXT PRIMARY KEY REFERENCES webhook_subscriptions(id) ON DELETE CASCADE,
                mode TEXT NOT NULL CHECK(mode IN ('immediate', 'daily_summary', 'subject_prep')),
                time_kst TEXT NOT NULL,
                subject TEXT,
                revision INTEGER NOT NULL CHECK(revision > 0),
                active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0, 1))
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS scheduled_occurrences (
                id INTEGER PRIMARY KEY,
                subscription_id TEXT NOT NULL REFERENCES webhook_subscriptions(id) ON DELETE CASCADE,
                scheduled_date TEXT NOT NULL,
                mode TEXT NOT NULL CHECK(mode IN ('daily_summary', 'subject_prep')),
                revision INTEGER NOT NULL,
                event_id TEXT NOT NULL,
                state TEXT NOT NULL CHECK(state IN ('queued', 'canceled', 'retired')),
                UNIQUE(subscription_id, scheduled_date, mode),
                UNIQUE(subscription_id, event_id)
            )
        """)
        db.execute("CREATE INDEX IF NOT EXISTS scheduled_occurrences_subscription_state "
                   "ON scheduled_occurrences(subscription_id, state)")
        db.execute("CREATE INDEX IF NOT EXISTS scheduled_occurrences_date ON scheduled_occurrences(scheduled_date)")

    @staticmethod
    def _authorized(db, subscription_id, token_hash):
        return bool(token_hash) and db.execute(
            "SELECT 1 FROM webhook_subscriptions WHERE id=? AND token_hash=?",
            (subscription_id, token_hash),
        ).fetchone() is not None

    @staticmethod
    def _cancel_occurrences(db, subscription_id):
        rows = db.execute(
            "SELECT o.event_id, d.state AS delivery_state FROM scheduled_occurrences o "
            "LEFT JOIN webhook_deliveries d ON d.subscription_id=o.subscription_id AND d.event_id=o.event_id "
            "WHERE o.subscription_id=? AND o.state='queued'",
            (subscription_id,),
        ).fetchall()
        for row in rows:
            if row["delivery_state"] == "pending":
                db.execute("DELETE FROM webhook_deliveries WHERE subscription_id=? AND event_id=? AND state='pending'",
                           (subscription_id, row["event_id"]))
                db.execute("UPDATE scheduled_occurrences SET state='canceled' WHERE subscription_id=? AND event_id=?",
                           (subscription_id, row["event_id"]))
            elif row["delivery_state"] == "leased":
                db.execute("UPDATE webhook_deliveries SET state='canceled', next_at=?, lease_token=NULL, lease_until=NULL "
                           "WHERE subscription_id=? AND event_id=? AND state='leased'",
                           (time.time(), subscription_id, row["event_id"]))
                db.execute("UPDATE scheduled_occurrences SET state='retired' WHERE subscription_id=? AND event_id=?",
                           (subscription_id, row["event_id"]))

    def set_schedule(self, subscription_id, token, mode, time_kst, subject=None):
        subject = self._validate_schedule(mode, time_kst, subject)
        token_hash = self._token_hash(token)
        with closing(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                if not self._authorized(db, subscription_id, token_hash):
                    db.execute("COMMIT")
                    return None
                self._ensure_schema(db)
                previous = db.execute(
                    "SELECT mode, time_kst, subject, revision, active FROM scheduled_settings WHERE subscription_id=?",
                    (subscription_id,),
                ).fetchone()
                if previous and previous["active"] and (previous["mode"], previous["time_kst"], previous["subject"]) == (mode, time_kst, subject):
                    db.execute("COMMIT")
                    return {"mode": mode, "time_kst": time_kst, "subject": subject, "revision": previous["revision"]}
                self._cancel_occurrences(db, subscription_id)
                revision = previous["revision"] + 1 if previous else 1
                db.execute(
                    "INSERT INTO scheduled_settings(subscription_id, mode, time_kst, subject, revision) "
                    "VALUES (?, ?, ?, ?, ?) ON CONFLICT(subscription_id) DO UPDATE SET "
                    "mode=excluded.mode, time_kst=excluded.time_kst, subject=excluded.subject, "
                    "revision=excluded.revision, active=1",
                    (subscription_id, mode, time_kst, subject, revision),
                )
                db.execute("COMMIT")
                return {"mode": mode, "time_kst": time_kst, "subject": subject, "revision": revision}
            except BaseException:
                db.execute("ROLLBACK")
                raise

    def get_schedule(self, subscription_id, token):
        token_hash = self._token_hash(token)
        with closing(self._connect()) as db:
            if not self._authorized(db, subscription_id, token_hash):
                return None
            self._ensure_schema(db)
            row = db.execute(
                "SELECT mode, time_kst, subject, revision FROM scheduled_settings "
                "WHERE subscription_id=? AND active=1",
                (subscription_id,),
            ).fetchone()
        return dict(row) if row else None

    def cancel_schedule(self, subscription_id, token):
        token_hash = self._token_hash(token)
        with closing(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                if not self._authorized(db, subscription_id, token_hash):
                    db.execute("COMMIT")
                    return False
                self._ensure_schema(db)
                self._cancel_occurrences(db, subscription_id)
                changed = db.execute(
                    "UPDATE scheduled_settings SET active=0 WHERE subscription_id=? AND active=1",
                    (subscription_id,),
                ).rowcount == 1
                db.execute("COMMIT")
                return changed
            except BaseException:
                db.execute("ROLLBACK")
                raise

    def active_schedules(self):
        """Read scheduler inputs without retaining management tokens."""
        with closing(self._connect()) as db:
            if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='scheduled_settings'").fetchone():
                return []
            rows = db.execute("""SELECT s.subscription_id, s.mode, s.time_kst, s.subject, s.revision,
                                  w.school, w.grade, w.classroom, w.provider, w.filters_json
                                  FROM scheduled_settings s JOIN webhook_subscriptions w ON w.id=s.subscription_id
                                  WHERE s.active=1 AND s.mode!='immediate'""").fetchall()
        return [dict(row) for row in rows]

    def prune_occurrences(self, today):
        """Expire old deduplication records without removing active deliveries."""
        if type(today) is not date:
            raise ValueError("invalid cleanup date")
        cutoff = (today - timedelta(days=31)).isoformat()
        with closing(self._connect()) as db:
            if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='scheduled_occurrences'").fetchone():
                return 0
            return db.execute("""DELETE FROM scheduled_occurrences WHERE scheduled_date<? AND NOT EXISTS (
                SELECT 1 FROM webhook_deliveries d WHERE d.subscription_id=scheduled_occurrences.subscription_id
                AND d.event_id=scheduled_occurrences.event_id AND d.state IN ('pending', 'leased'))""", (cutoff,)).rowcount

    def mark_noop(self, subscription_id, expected_revision, scheduled_date, *, expected_filters="{}"):
        """Record an observed empty result without reserving a delivery."""
        try:
            parsed_date = date.fromisoformat(scheduled_date)
        except (TypeError, ValueError):
            raise ValueError("invalid scheduled_date") from None
        if parsed_date.isoformat() != scheduled_date or type(expected_revision) is not int or expected_revision < 1:
            raise ValueError("invalid occurrence")
        with closing(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                self._ensure_schema(db)
                setting = db.execute("SELECT s.mode FROM scheduled_settings s JOIN webhook_subscriptions w ON w.id=s.subscription_id "
                                     "WHERE s.subscription_id=? AND s.revision=? AND s.active=1 AND w.filters_json=?",
                                     (subscription_id, expected_revision, expected_filters)).fetchone()
                if not setting or setting["mode"] == "immediate":
                    db.execute("COMMIT")
                    return False
                event_id = scheduled_event_id(subscription_id, setting["mode"], parsed_date)
                inserted = db.execute("INSERT INTO scheduled_occurrences(subscription_id, scheduled_date, mode, revision, event_id, state) "
                                      "VALUES (?, ?, ?, ?, ?, 'retired') ON CONFLICT(subscription_id, scheduled_date, mode) "
                                      "DO UPDATE SET revision=excluded.revision, state='retired' WHERE scheduled_occurrences.state='canceled'",
                                      (subscription_id, scheduled_date, setting["mode"], expected_revision, event_id)).rowcount == 1
                db.execute("COMMIT")
                return inserted
            except BaseException:
                db.execute("ROLLBACK")
                raise

    def already_handled(self, subscription_id, mode, scheduled_date):
        with closing(self._connect()) as db:
            row = db.execute("SELECT state FROM scheduled_occurrences WHERE subscription_id=? AND mode=? AND scheduled_date=?",
                             (subscription_id, mode, scheduled_date)).fetchone()
        return bool(row and row["state"] != "canceled")

    def enqueue_due(self, subscription_id, expected_revision, scheduled_date, body, due_at, *, expected_filters="{}"):
        """Atomically enqueue a prepared occurrence from the trusted scheduler."""
        try:
            parsed_date = date.fromisoformat(scheduled_date)
        except (TypeError, ValueError):
            raise ValueError("invalid scheduled_date") from None
        if parsed_date.isoformat() != scheduled_date:
            raise ValueError("invalid scheduled_date")
        if type(expected_revision) is not int or expected_revision < 1:
            raise ValueError("invalid schedule revision")
        if not isinstance(body, bytes) or not body or len(body) > 65536:
            raise ValueError("invalid body")
        try:
            json.loads(body)
        except (ValueError, UnicodeDecodeError):
            raise ValueError("invalid JSON body") from None
        if isinstance(due_at, bool) or not isinstance(due_at, (int, float)):
            raise ValueError("due_at must be a timestamp")
        if not math.isfinite(due_at):
            raise ValueError("due_at must be finite")
        with closing(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                self._ensure_schema(db)
                setting = db.execute("SELECT s.revision, s.mode FROM scheduled_settings s "
                                     "JOIN webhook_subscriptions w ON w.id=s.subscription_id "
                                     "WHERE s.subscription_id=? AND s.active=1 AND s.revision=? AND w.filters_json=?",
                                     (subscription_id, expected_revision, expected_filters)).fetchone()
                if setting is None or setting["mode"] == "immediate":
                    db.execute("COMMIT")
                    return False
                event_id = scheduled_event_id(subscription_id, setting["mode"], parsed_date)
                occurrence = db.execute(
                    "SELECT state FROM scheduled_occurrences WHERE subscription_id=? AND scheduled_date=? AND mode=?",
                    (subscription_id, scheduled_date, setting["mode"]),
                ).fetchone()
                if occurrence and occurrence["state"] != "canceled":
                    db.execute("COMMIT")
                    return False
                pending = db.execute("SELECT COUNT(*) FROM webhook_deliveries WHERE subscription_id=? AND state IN ('pending', 'leased')",
                                     (subscription_id,)).fetchone()[0]
                if pending >= MAX_PENDING_PER_SUBSCRIPTION:
                    db.execute("COMMIT")
                    return False
                inserted = db.execute("INSERT OR IGNORE INTO webhook_deliveries(subscription_id, event_id, body, next_at) VALUES (?, ?, ?, ?)",
                                      (subscription_id, event_id, body, float(due_at))).rowcount == 1
                if inserted:
                    db.execute("INSERT INTO scheduled_occurrences(subscription_id, scheduled_date, mode, revision, event_id, state) "
                               "VALUES (?, ?, ?, ?, ?, 'queued') ON CONFLICT(subscription_id, scheduled_date, mode) "
                               "DO UPDATE SET revision=excluded.revision, event_id=excluded.event_id, state='queued'",
                               (subscription_id, scheduled_date, setting["mode"], expected_revision, event_id))
                db.execute("COMMIT")
                return inserted
            except BaseException:
                db.execute("ROLLBACK")
                raise
