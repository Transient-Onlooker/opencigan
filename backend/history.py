"""SQLite-backed timetable change history."""

import json
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path


class HistoryStore:
    def __init__(self, path):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS snapshots (
                    school TEXT NOT NULL, week TEXT NOT NULL,
                    grade INTEGER NOT NULL, class_number INTEGER NOT NULL,
                    date TEXT NOT NULL, period INTEGER NOT NULL,
                    subject TEXT NOT NULL, teacher TEXT NOT NULL,
                    PRIMARY KEY (school, week, grade, class_number, date, period)
                );
                CREATE TABLE IF NOT EXISTS changes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    school TEXT NOT NULL, week TEXT NOT NULL,
                    observed_at TEXT NOT NULL, grade INTEGER NOT NULL,
                    class_number INTEGER NOT NULL, date TEXT NOT NULL,
                    period INTEGER NOT NULL, type TEXT NOT NULL,
                    before_json TEXT, after_json TEXT
                );
                CREATE TABLE IF NOT EXISTS observed_weeks (
                    school TEXT NOT NULL, week TEXT NOT NULL, observed_at TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    PRIMARY KEY (school, week)
                );
                CREATE INDEX IF NOT EXISTS changes_scope_id
                    ON changes(school, week, id);
                CREATE INDEX IF NOT EXISTS changes_observed_at
                    ON changes(observed_at);
                CREATE TABLE IF NOT EXISTS snapshot_lessons (
                    school TEXT NOT NULL, week TEXT NOT NULL,
                    grade INTEGER NOT NULL, class_number INTEGER NOT NULL,
                    date TEXT NOT NULL, period INTEGER NOT NULL, position INTEGER NOT NULL,
                    subject TEXT NOT NULL, teacher TEXT NOT NULL,
                    PRIMARY KEY (school, week, grade, class_number, date, period, position)
                );
                CREATE TABLE IF NOT EXISTS history_migrations (name TEXT PRIMARY KEY);
            """)
            db.execute("BEGIN IMMEDIATE")
            try:
                migrated = db.execute("SELECT 1 FROM history_migrations WHERE name=?", ("snapshot_lessons_v1",)).fetchone()
                if not migrated:
                    db.execute("""INSERT INTO snapshot_lessons
                        SELECT school, week, grade, class_number, date, period, 0, subject, teacher FROM snapshots""")
                    db.execute("INSERT INTO history_migrations VALUES (?)", ("snapshot_lessons_v1",))
                db.execute("COMMIT")
            except BaseException:
                db.execute("ROLLBACK")
                raise

    def _connect(self):
        db = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=30000")
        if self.path != ":memory:":
            db.execute("PRAGMA journal_mode=WAL")
        return db

    @staticmethod
    def _value(record):
        return {"subject": record.get("subject") or "",
                "teacher": record.get("teacher") or ""}

    @staticmethod
    def _timestamp(value):
        if isinstance(value, datetime):
            parsed = value
        else:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).isoformat()

    def observe(self, school, week, records, observed_at=None, started_at=None):
        timestamp = self._timestamp(observed_at or datetime.now(timezone.utc))
        request_started = self._timestamp(started_at or timestamp)
        cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        current = {}
        for record in records:
            key = (record["grade"], record["class"], record["date"], record["period"])
            current.setdefault(key, []).append(self._value(record))
        for values in current.values():
            values.sort(key=lambda value: (value["subject"], value["teacher"]))

        with closing(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                db.execute("DELETE FROM changes WHERE observed_at < ?", (cutoff,))
                expired = db.execute("SELECT school, week FROM observed_weeks WHERE observed_at < ?", (cutoff,)).fetchall()
                for old in expired:
                    db.execute("DELETE FROM snapshots WHERE school=? AND week=?", (old["school"], old["week"]))
                    db.execute("DELETE FROM snapshot_lessons WHERE school=? AND week=?", (old["school"], old["week"]))
                db.execute("DELETE FROM observed_weeks WHERE observed_at < ?", (cutoff,))
                prior_rows = db.execute(
                    "SELECT grade, class_number, date, period, subject, teacher FROM snapshot_lessons "
                    "WHERE school=? AND week=?", (school, week)).fetchall()
                prior = {}
                for row in prior_rows:
                    key = (row["grade"], row["class_number"], row["date"], row["period"])
                    prior.setdefault(key, []).append({"subject": row["subject"], "teacher": row["teacher"]})
                # An absent snapshot is the first observation: establish baseline only.
                has_baseline = db.execute(
                    "SELECT 1 FROM observed_weeks WHERE school=? AND week=?",
                    (school, week)).fetchone() is not None
                if has_baseline:
                    latest = db.execute("SELECT started_at FROM observed_weeks WHERE school=? AND week=?",
                                        (school, week)).fetchone()["started_at"]
                    if request_started < latest:
                        db.execute("COMMIT")
                        return
                if has_baseline:
                    webhooks_enabled = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='webhook_subscriptions'").fetchone() is not None
                    if webhooks_enabled:
                        from backend.webhook_store import enqueue_observed_change
                    for key in sorted(prior.keys() | current.keys()):
                        old = sorted(prior.get(key, []), key=lambda value: (value["subject"], value["teacher"]))
                        new = list(current.get(key, []))
                        for lesson in old[:]:
                            if lesson in new:
                                old.remove(lesson)
                                new.remove(lesson)
                        while old or new:
                            before = old.pop(0) if old else None
                            after = new.pop(0) if new else None
                            kind = "added" if before is None else "deleted" if after is None else "changed"
                            cursor = db.execute("""INSERT INTO changes
                            (school, week, observed_at, grade, class_number, date, period,
                             type, before_json, after_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                            (school, week, timestamp, *key, kind,
                             json.dumps(before, ensure_ascii=False) if before is not None else None,
                             json.dumps(after, ensure_ascii=False) if after is not None else None))
                            if webhooks_enabled:
                                enqueue_observed_change(db, school, key[0], key[1], key[2], key[3], kind,
                                                        before, after, cursor.lastrowid, datetime.now(timezone.utc).timestamp())
                db.execute("DELETE FROM snapshot_lessons WHERE school=? AND week=?", (school, week))
                db.execute("INSERT INTO observed_weeks VALUES (?, ?, ?, ?) ON CONFLICT(school, week) DO UPDATE SET observed_at=excluded.observed_at, started_at=excluded.started_at", (school, week, timestamp, request_started))
                db.executemany("""INSERT INTO snapshot_lessons
                    (school, week, grade, class_number, date, period, position, subject, teacher)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    [(school, week, *key, position, value["subject"], value["teacher"])
                     for key, values in current.items() for position, value in enumerate(values)])
                db.execute("COMMIT")
            except BaseException:
                db.execute("ROLLBACK")
                raise

    def list(self, school, week, cursor=None, limit=50, grade=None, classroom=None, include_ids=False, filters=None):
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
            raise ValueError("limit must be a positive integer")
        if cursor is None:
            before_id = (1 << 63) - 1
        else:
            if not isinstance(cursor, (str, int)) or isinstance(cursor, bool):
                raise ValueError("cursor must be a positive integer")
            raw_cursor = str(cursor)
            if not raw_cursor.isascii() or not raw_cursor.isdecimal() or raw_cursor.startswith("0"):
                raise ValueError("cursor must be a positive integer")
            before_id = int(raw_cursor)
            if before_id < 1 or before_id >= (1 << 63):
                raise ValueError("cursor must be a positive integer")
        cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        with closing(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM changes WHERE observed_at < ?", (cutoff,))
            expired = db.execute("SELECT school, week FROM observed_weeks WHERE observed_at < ?", (cutoff,)).fetchall()
            for old in expired:
                db.execute("DELETE FROM snapshots WHERE school=? AND week=?", (old["school"], old["week"]))
                db.execute("DELETE FROM snapshot_lessons WHERE school=? AND week=?", (old["school"], old["week"]))
            db.execute("DELETE FROM observed_weeks WHERE observed_at < ?", (cutoff,))
            db.execute("COMMIT")
            filters = filters or {}
            rows = db.execute("""SELECT id, observed_at, grade, class_number, date,
                    period, type, before_json, after_json FROM changes
                    WHERE school=? AND week=? AND observed_at>=? AND id<?
                    AND (? IS NULL OR grade=?) AND (? IS NULL OR class_number=?)
                    AND (? IS NULL OR period=?) AND (? IS NULL OR type=?)
                    AND (? IS NULL OR strftime('%w', date)=?)
                    AND (? IS NULL OR instr(COALESCE(json_extract(before_json, '$.subject'), ''), ?) > 0
                         OR instr(COALESCE(json_extract(after_json, '$.subject'), ''), ?) > 0)
                    AND (? IS NULL OR instr(COALESCE(json_extract(before_json, '$.teacher'), ''), ?) > 0
                         OR instr(COALESCE(json_extract(after_json, '$.teacher'), ''), ?) > 0)
                    ORDER BY id DESC LIMIT ?""",
                (school, week, cutoff, before_id, grade, grade, classroom, classroom,
                 filters.get("period"), filters.get("period"), filters.get("type"), filters.get("type"),
                 filters.get("weekday"), filters.get("weekday"),
                 filters.get("subject"), filters.get("subject"), filters.get("subject"),
                 filters.get("teacher"), filters.get("teacher"), filters.get("teacher"), limit + 1)).fetchall()
        more = len(rows) > limit
        rows = rows[:limit]
        changes = [{"observedAt": r["observed_at"], "grade": r["grade"],
                    "class": r["class_number"], "date": r["date"],
                    "period": r["period"], "type": r["type"],
                    "before": json.loads(r["before_json"]) if r["before_json"] else None,
                    "after": json.loads(r["after_json"]) if r["after_json"] else None}
                   for r in rows]
        if include_ids:
            for change, row in zip(changes, rows):
                change["_id"] = row["id"]
        next_cursor = str(rows[-1]["id"]) if more and rows else None
        return {"changes": changes, "nextCursor": next_cursor}
