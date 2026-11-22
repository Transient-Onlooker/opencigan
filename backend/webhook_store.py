"""SQLite subscription and delivery queue; not exposed until connected to the API."""

import hashlib
import json
import os
import re
import secrets
import sqlite3
import time
from contextlib import closing
from datetime import date as date_type, datetime, timedelta, timezone

from backend.webhook_delivery import validate_destination


class SubscriptionLimitError(Exception):
    pass


MAX_PENDING_PER_SUBSCRIPTION = 1000
MAX_DELIVERY_ATTEMPTS = 6
DELIVERY_RETENTION_SECONDS = 30 * 24 * 60 * 60


def validate_filters(filters):
    if not isinstance(filters, dict) or set(filters) - {"subject", "teacher", "weekday", "period", "type", "quietHours"}:
        raise ValueError("invalid filters")
    for key, value in filters.items():
        if key in ("subject", "teacher"):
            if not isinstance(value, str) or not value.strip() or len(value) > 50:
                raise ValueError("invalid filter")
        elif key in ("weekday", "period"):
            if type(value) is not int or not 1 <= value <= (5 if key == "weekday" else 20):
                raise ValueError("invalid filter")
        elif key == "quietHours":
            if (not isinstance(value, dict) or set(value) != {"start", "end"}
                    or any(not isinstance(value[k], str) or not re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", value[k]) for k in ("start", "end"))
                    or value["start"] == value["end"]):
                raise ValueError("invalid quiet hours")
        elif value not in ("added", "deleted", "changed"):
            raise ValueError("invalid filter")
    return filters


def quiet_until(now, quiet_hours):
    if not quiet_hours:
        return None
    local = datetime.fromtimestamp(now, timezone(timedelta(hours=9)))
    current = local.hour * 60 + local.minute
    start = int(quiet_hours["start"][:2]) * 60 + int(quiet_hours["start"][3:])
    end = int(quiet_hours["end"][:2]) * 60 + int(quiet_hours["end"][3:])
    if not (start <= current < end if start < end else current >= start or current < end):
        return None
    target = local.replace(hour=end // 60, minute=end % 60, second=0, microsecond=0)
    if start > end and current >= start:
        target += timedelta(days=1)
    return target.timestamp()


def enqueue_observed_change(db, school, grade, classroom, date, period, kind, before, after, change_id, now):
    subscriptions = db.execute("SELECT id, provider, filters_json FROM webhook_subscriptions WHERE school=? AND grade=? AND classroom=?",
                               (school, grade, classroom)).fetchall()
    if not subscriptions:
        return

    def lesson(value):
        if value is None:
            return "없음"
        return " · ".join(part for part in (value.get("subject"), value.get("teacher")) if part) or "정보 없음"

    text = f"{school.split(':', 1)[-1]} {grade}학년 {classroom}반 · {date} {period}교시 ({kind})\n{lesson(before)} → {lesson(after)}"
    # Google Chat interprets angle-bracket tokens as mentions; Discord disables all mentions explicitly.
    safe_text = text.replace("<", "＜").replace(">", "＞")[:1800]
    for subscription in subscriptions:
        filters = json.loads(subscription["filters_json"])
        if any(filters.get(key) is not None and filters[key] != value for key, value in
               (("period", period), ("type", kind), ("weekday", date_type.fromisoformat(date).isoweekday()))):
            continue
        if any(filters.get(key) and not any(filters[key] in (value or {}).get(key, "") for value in (before, after))
               for key in ("subject", "teacher")):
            continue
        if db.execute("SELECT COUNT(*) FROM webhook_deliveries WHERE subscription_id=? AND state IN ('pending', 'leased')", (subscription["id"],)).fetchone()[0] >= MAX_PENDING_PER_SUBSCRIPTION:
            db.execute("UPDATE webhook_subscriptions SET dropped_events=dropped_events+1 WHERE id=?", (subscription["id"],))
            continue
        payload = {"content": safe_text, "allowed_mentions": {"parse": []}} if subscription["provider"] == "discord" else {"text": safe_text}
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        db.execute("INSERT OR IGNORE INTO webhook_deliveries(subscription_id, event_id, body, next_at) VALUES (?, ?, ?, ?)",
                   (subscription["id"], f"change_{change_id}", body, now))


class WebhookStore:
    def __init__(self, path):
        self.path = str(path)
        if self.path == ":memory:":
            raise ValueError("webhook queue requires a persistent database")
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            pass
        else:
            os.close(fd)
        with closing(self._connect()) as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS webhook_subscriptions (
                    id TEXT PRIMARY KEY, token_hash TEXT NOT NULL, school TEXT NOT NULL,
                    grade INTEGER NOT NULL, classroom INTEGER NOT NULL, destination TEXT NOT NULL,
                    provider TEXT NOT NULL, signing_secret BLOB NOT NULL
                );
                CREATE TABLE IF NOT EXISTS webhook_deliveries (
                    id INTEGER PRIMARY KEY, subscription_id TEXT NOT NULL REFERENCES webhook_subscriptions(id) ON DELETE CASCADE,
                    event_id TEXT NOT NULL, body BLOB NOT NULL, state TEXT NOT NULL DEFAULT 'pending',
                    attempts INTEGER NOT NULL DEFAULT 0, next_at REAL NOT NULL,
                    lease_token TEXT, lease_until REAL, last_status INTEGER,
                    UNIQUE(subscription_id, event_id)
                );
                CREATE INDEX IF NOT EXISTS webhook_ready ON webhook_deliveries(state, next_at, lease_until);
                CREATE INDEX IF NOT EXISTS webhook_subscription_state ON webhook_deliveries(subscription_id, state);
            """)
            db.execute("BEGIN IMMEDIATE")
            try:
                columns = {row["name"] for row in db.execute("PRAGMA table_info(webhook_subscriptions)")}
                if "dropped_events" not in columns:
                    db.execute("ALTER TABLE webhook_subscriptions ADD COLUMN dropped_events INTEGER NOT NULL DEFAULT 0")
                if "last_test_at" not in columns:
                    db.execute("ALTER TABLE webhook_subscriptions ADD COLUMN last_test_at REAL")
                if "filters_json" not in columns:
                    db.execute("ALTER TABLE webhook_subscriptions ADD COLUMN filters_json TEXT NOT NULL DEFAULT '{}' ")
                db.execute("COMMIT")
            except BaseException:
                db.execute("ROLLBACK")
                raise

    def _connect(self):
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        return db

    @staticmethod
    def _token_hash(token):
        if not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
            return ""
        return hashlib.sha256(token.encode("ascii")).hexdigest()

    def create(self, school, grade, classroom, destination):
        provider = validate_destination(destination)
        if not isinstance(school, str) or not re.fullmatch(r"[0-9]+:[^:\x00-\x1f\x7f]{1,50}", school):
            raise ValueError("invalid school")
        if type(grade) is not int or not 1 <= grade <= 6 or type(classroom) is not int or not 1 <= classroom <= 99:
            raise ValueError("invalid class")
        identifier, token = secrets.token_urlsafe(18), secrets.token_urlsafe(32)
        with closing(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                if db.execute("SELECT COUNT(*) FROM webhook_subscriptions").fetchone()[0] >= 500:
                    raise SubscriptionLimitError()
                db.execute("INSERT INTO webhook_subscriptions(id, token_hash, school, grade, classroom, destination, provider, signing_secret) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                           (identifier, self._token_hash(token), school, grade, classroom, destination, provider, secrets.token_bytes(32)))
                db.execute("COMMIT")
            except BaseException:
                db.execute("ROLLBACK")
                raise
        return {"id": identifier, "token": token, "provider": provider}

    def get(self, identifier, token):
        with closing(self._connect()) as db:
            row = db.execute("SELECT id, school, grade, classroom, provider, dropped_events, filters_json FROM webhook_subscriptions WHERE id=? AND token_hash=?",
                             (identifier, self._token_hash(token))).fetchone()
        if not row:
            return None
        result = dict(row)
        result["filters"] = json.loads(result.pop("filters_json"))
        return result

    def rotate(self, identifier, token, new_token):
        new_hash = self._token_hash(new_token)
        if not new_hash or new_hash == self._token_hash(token):
            raise ValueError("invalid new token")
        with closing(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                updated = db.execute("UPDATE webhook_subscriptions SET token_hash=? WHERE id=? AND token_hash=?",
                                     (new_hash, identifier, self._token_hash(token))).rowcount == 1
                db.execute("COMMIT")
                return {"rotated": True} if updated else None
            except BaseException:
                db.execute("ROLLBACK")
                raise

    def update_filters(self, identifier, token, filters):
        validate_filters(filters)
        with closing(self._connect()) as db:
            return db.execute("UPDATE webhook_subscriptions SET filters_json=? WHERE id=? AND token_hash=?",
                              (json.dumps(filters, ensure_ascii=False), identifier, self._token_hash(token))).rowcount == 1

    def delete(self, identifier, token):
        with closing(self._connect()) as db:
            return db.execute("DELETE FROM webhook_subscriptions WHERE id=? AND token_hash=?", (identifier, self._token_hash(token))).rowcount == 1

    def deliveries(self, identifier, token):
        with closing(self._connect()) as db:
            if not db.execute("SELECT 1 FROM webhook_subscriptions WHERE id=? AND token_hash=?", (identifier, self._token_hash(token))).fetchone():
                return None
            rows = db.execute("""SELECT event_id, state, attempts, next_at, last_status FROM webhook_deliveries
                                 WHERE subscription_id=? ORDER BY id DESC LIMIT 50""", (identifier,)).fetchall()
        return [dict(row) for row in rows]

    def enqueue_test(self, identifier, token, now=None):
        now = time.time() if now is None else now
        with closing(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                row = db.execute("SELECT provider, last_test_at FROM webhook_subscriptions WHERE id=? AND token_hash=?",
                                 (identifier, self._token_hash(token))).fetchone()
                if not row:
                    db.execute("COMMIT")
                    return None
                recent = row["last_test_at"] is not None and row["last_test_at"] > now - 60
                pending = db.execute("SELECT COUNT(*) FROM webhook_deliveries WHERE subscription_id=? AND state IN ('pending', 'leased')", (identifier,)).fetchone()[0]
                if recent or pending >= MAX_PENDING_PER_SUBSCRIPTION:
                    db.execute("COMMIT")
                    return False
                event_id = "test_" + secrets.token_urlsafe(18)
                text = "OpenCigan 테스트 알림입니다. 이 메시지는 시간표 변경이 아닙니다."
                payload = {"content": text, "allowed_mentions": {"parse": []}} if row["provider"] == "discord" else {"text": text}
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                db.execute("INSERT INTO webhook_deliveries(subscription_id, event_id, body, next_at) VALUES (?, ?, ?, ?)", (identifier, event_id, body, now))
                db.execute("UPDATE webhook_subscriptions SET last_test_at=? WHERE id=?", (now, identifier))
                db.execute("COMMIT")
                return event_id
            except BaseException:
                db.execute("ROLLBACK")
                raise

    def enqueue(self, identifier, event_id, body, now=None):
        if not isinstance(event_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", event_id):
            raise ValueError("invalid event ID")
        if not isinstance(body, bytes) or not body or len(body) > 65536:
            raise ValueError("invalid body")
        try:
            json.loads(body)
        except (ValueError, UnicodeDecodeError):
            raise ValueError("invalid JSON body") from None
        with closing(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                if db.execute("SELECT COUNT(*) FROM webhook_deliveries WHERE subscription_id=? AND state IN ('pending', 'leased')", (identifier,)).fetchone()[0] >= MAX_PENDING_PER_SUBSCRIPTION:
                    db.execute("COMMIT")
                    return False
                inserted = db.execute("INSERT OR IGNORE INTO webhook_deliveries(subscription_id, event_id, body, next_at) VALUES (?, ?, ?, ?)",
                                      (identifier, event_id, body, time.time() if now is None else now)).rowcount == 1
                db.execute("COMMIT")
                return inserted
            except BaseException:
                db.execute("ROLLBACK")
                raise

    def claim(self, now=None, lease_seconds=60):
        now = time.time() if now is None else now
        lease_token = secrets.token_urlsafe(18)
        with closing(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                db.execute("DELETE FROM webhook_deliveries WHERE state IN ('delivered', 'failed') AND next_at<?", (now - DELIVERY_RETENTION_SECONDS,))
                db.execute("UPDATE webhook_deliveries SET state='failed', next_at=?, lease_token=NULL, lease_until=NULL WHERE state='leased' AND lease_until<=? AND attempts>=?", (now, now, MAX_DELIVERY_ATTEMPTS))
                while True:
                    row = db.execute("""SELECT d.id, d.event_id, d.body, d.attempts, s.destination, s.signing_secret, s.filters_json
                        FROM webhook_deliveries d JOIN webhook_subscriptions s ON s.id=d.subscription_id
                        WHERE (d.state='pending' AND d.next_at<=?) OR (d.state='leased' AND d.lease_until<=?)
                        ORDER BY d.next_at, d.id LIMIT 1""", (now, now)).fetchone()
                    if not row:
                        break
                    resume_at = None if row["event_id"].startswith("test_") else quiet_until(now, json.loads(row["filters_json"]).get("quietHours"))
                    if resume_at is None:
                        break
                    db.execute("UPDATE webhook_deliveries SET state='pending', next_at=?, lease_token=NULL, lease_until=NULL WHERE id=?", (resume_at, row["id"]))
                if row:
                    db.execute("UPDATE webhook_deliveries SET state='leased', attempts=attempts+1, lease_token=?, lease_until=? WHERE id=?",
                               (lease_token, now + lease_seconds, row["id"]))
                db.execute("COMMIT")
            except BaseException:
                db.execute("ROLLBACK")
                raise
        return {**dict(row), "leaseToken": lease_token, "attempt": row["attempts"] + 1} if row else None

    def finish(self, delivery_id, lease_token, result, now=None, max_attempts=MAX_DELIVERY_ATTEMPTS):
        now = time.time() if now is None else now
        with closing(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                row = db.execute("SELECT attempts FROM webhook_deliveries WHERE id=? AND state='leased' AND lease_token=?", (delivery_id, lease_token)).fetchone()
                if not row:
                    db.execute("COMMIT")
                    return False
                if result["delivered"]:
                    state, next_at = "delivered", now
                elif result["retryable"] and row["attempts"] < max_attempts:
                    delay = min(3600, max(2 ** row["attempts"] * 15, result.get("retryAfter") or 0))
                    state, next_at = "pending", now + delay
                else:
                    state, next_at = "failed", now
                db.execute("UPDATE webhook_deliveries SET state=?, next_at=?, last_status=?, lease_token=NULL, lease_until=NULL WHERE id=?",
                           (state, next_at, result.get("status"), delivery_id))
                db.execute("COMMIT")
                return True
            except BaseException:
                db.execute("ROLLBACK")
                raise
