"""Persistent deduplication and delivery state for administrator alerts."""

import hashlib
import hmac
import ipaddress
import json
import math
import os
import secrets
import sqlite3
import stat
from contextlib import closing
from pathlib import Path


_MAX_ATTEMPTS = 6
_BASE_RETRY_SECONDS = 60
_MAX_RETRY_SECONDS = 3600
_RETENTION_SECONDS = 31 * 24 * 60 * 60
_MAX_FINDINGS = 1000
_MAX_STORE_ROWS = 50000
_MAX_DB_BYTES = 32 * 1024 * 1024
_KINDS = {"status_errors", "request_volume", "error_ratio", "school_scan"}
_STATUS_GROUPS = {"404", "429", "5xx"}
_STORE_MARKER = "opencigan-admin-alert-store-v1"


def _timestamp(value, name):
    if value is None:
        import time

        value = time.time()
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite timestamp")
    return float(value)


class AdminAlertStore:
    """Store alert episodes and a retryable outbox in a separate SQLite file."""

    def __init__(self, path, hmac_key):
        if not isinstance(hmac_key, bytes) or len(hmac_key) < 32:
            raise ValueError("hmac_key must contain at least 32 bytes")
        if not isinstance(path, (str, os.PathLike)) or not str(path).strip() or str(path) == ":memory:":
            raise ValueError("a persistent alert database path is required")

        self.path = Path(path).absolute()
        self.hmac_key = hmac_key
        self._initialized = False
        if self.path.is_symlink():
            raise ValueError("alert database path must not be a symbolic link")
        created = False
        try:
            flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            descriptor = os.open(self.path, flags, 0o600)
        except FileExistsError:
            pass
        else:
            os.close(descriptor)
            created = True

        file_stat = self.path.lstat()
        if not stat.S_ISREG(file_stat.st_mode):
            raise ValueError("alert database path must be a regular file")
        if os.name != "nt" and file_stat.st_mode & 0o077:
            raise PermissionError("alert database permissions must be 0600")

        with closing(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                objects = {row[0] for row in db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
                if not created:
                    if not objects:
                        raise ValueError("existing database has no administrator alert store identity")
                    if objects - {"admin_alert_store_meta", "admin_alerts", "admin_alert_deliveries"}:
                        raise ValueError("database contains tables outside the administrator alert store")
                    if "admin_alert_store_meta" not in objects:
                        raise ValueError("database is not an administrator alert store")
                    row = db.execute("SELECT marker FROM admin_alert_store_meta WHERE id=1").fetchone()
                    if row is None or row[0] != _STORE_MARKER:
                        raise ValueError("database is not an administrator alert store")

                page_size = db.execute("PRAGMA page_size").fetchone()[0]
                page_limit = _MAX_DB_BYTES // page_size
                page_count = db.execute("PRAGMA page_count").fetchone()[0]
                if page_count * page_size > _MAX_DB_BYTES:
                    raise AdminAlertStoreCapacityError("alert database exceeds its size limit")
                db.execute(f"PRAGMA max_page_count={page_limit}")
                db.execute("""CREATE TABLE IF NOT EXISTS admin_alert_store_meta (
                    id INTEGER PRIMARY KEY CHECK(id=1),
                    marker TEXT NOT NULL
                )""")
                db.execute("""CREATE TABLE IF NOT EXISTS admin_alerts (
                    fingerprint TEXT PRIMARY KEY,
                    episode_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    status_group TEXT,
                    state TEXT NOT NULL CHECK(state IN ('active', 'resolved')),
                    first_seen REAL NOT NULL,
                    last_seen REAL NOT NULL,
                    resolved_at REAL
                )""")
                db.execute("""CREATE TABLE IF NOT EXISTS admin_alert_deliveries (
                    id TEXT PRIMARY KEY,
                    fingerprint TEXT NOT NULL,
                    episode_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    state TEXT NOT NULL CHECK(state IN ('pending', 'leased', 'delivered', 'failed', 'canceled')),
                    attempts INTEGER NOT NULL DEFAULT 0 CHECK(attempts >= 0),
                    next_at REAL NOT NULL,
                    lease_token TEXT,
                    lease_until REAL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    delivered_at REAL,
                    UNIQUE(fingerprint, episode_id)
                )""")
                db.execute("CREATE INDEX IF NOT EXISTS admin_alert_delivery_ready "
                           "ON admin_alert_deliveries(state, next_at, lease_until, created_at)")
                db.execute("INSERT OR IGNORE INTO admin_alert_store_meta(id, marker) VALUES (1, ?)",
                           (_STORE_MARKER,))
                db.execute("COMMIT")
                self._initialized = True
            except BaseException:
                db.execute("ROLLBACK")
                raise

    def _connect(self):
        total_size = 0
        for candidate in (self.path, Path(str(self.path) + "-wal"),
                          Path(str(self.path) + "-shm"), Path(str(self.path) + "-journal")):
            try:
                candidate_stat = candidate.lstat()
            except FileNotFoundError:
                continue
            if stat.S_ISLNK(candidate_stat.st_mode) or not stat.S_ISREG(candidate_stat.st_mode):
                raise ValueError("alert database and SQLite sidecars must be regular non-link files")
            if os.name != "nt" and candidate_stat.st_mode & 0o077:
                raise PermissionError("alert database and SQLite sidecars must be private")
            total_size += candidate_stat.st_size
        if total_size > _MAX_DB_BYTES:
            raise AdminAlertStoreCapacityError("alert database and sidecars exceed their size limit")
        uri = self.path.as_uri() + "?mode=rw"
        db = sqlite3.connect(uri, uri=True, timeout=10, isolation_level=None)
        db.row_factory = sqlite3.Row
        if self._initialized:
            marker = db.execute("SELECT marker FROM admin_alert_store_meta WHERE id=1").fetchone()
            if marker is None or marker[0] != _STORE_MARKER:
                db.close()
                raise ValueError("database is not an administrator alert store")
            page_size = db.execute("PRAGMA page_size").fetchone()[0]
            page_count = db.execute("PRAGMA page_count").fetchone()[0]
            if page_count * page_size > _MAX_DB_BYTES:
                db.close()
                raise AdminAlertStoreCapacityError("alert database exceeds its size limit")
            db.execute(f"PRAGMA max_page_count={_MAX_DB_BYTES // page_size}")
        return db

    def _prepare_finding(self, finding):
        if not isinstance(finding, dict):
            raise ValueError("finding must be an object")
        raw_ip = finding.get("client_ip")
        if not isinstance(raw_ip, str):
            raise ValueError("finding client_ip must be an IP address")
        try:
            client_ip = ipaddress.ip_address(raw_ip).compressed
        except ValueError:
            raise ValueError("finding client_ip must be an IP address") from None

        kind = finding.get("kind")
        status_group = finding.get("status_group")
        if kind not in _KINDS or (kind == "status_errors" and status_group not in _STATUS_GROUPS):
            raise ValueError("invalid finding kind")
        if kind != "status_errors" and status_group is not None:
            raise ValueError("status_group is only valid for status_errors")

        identity = json.dumps((client_ip, kind, status_group), separators=(",", ":"), ensure_ascii=True)
        fingerprint = hmac.new(self.hmac_key, identity.encode("ascii"), hashlib.sha256).hexdigest()
        payload = {"kind": kind}
        if status_group is not None:
            payload["status_group"] = status_group
        return fingerprint, kind, status_group, json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

    def sync_findings(self, findings, *, now=None):
        """Reconcile active findings and atomically enqueue each new episode."""
        now = _timestamp(now, "now")
        if not isinstance(findings, (list, tuple)):
            raise ValueError("findings must be a list")
        if len(findings) > _MAX_FINDINGS:
            raise AdminAlertStoreCapacityError("anomaly query result exceeds its item limit")

        prepared = {}
        for finding in findings:
            fingerprint, kind, status_group, payload = self._prepare_finding(finding)
            prepared[fingerprint] = (kind, status_group, payload)

        self.prune(now=now)
        created = 0
        with closing(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                active = {row[0] for row in db.execute(
                    "SELECT fingerprint FROM admin_alerts WHERE state='active'")}
                for fingerprint in active - prepared.keys():
                    row = db.execute("SELECT episode_id FROM admin_alerts WHERE fingerprint=?",
                                     (fingerprint,)).fetchone()
                    db.execute("UPDATE admin_alerts SET state='resolved', resolved_at=? WHERE fingerprint=?",
                               (now, fingerprint))
                    db.execute("UPDATE admin_alert_deliveries SET state='canceled', lease_token=NULL, "
                               "lease_until=NULL, updated_at=? WHERE fingerprint=? AND episode_id=? "
                               "AND state IN ('pending', 'leased')", (now, fingerprint, row["episode_id"]))

                new_fingerprints = prepared.keys() - active
                alert_count = db.execute("SELECT COUNT(*) FROM admin_alerts").fetchone()[0]
                delivery_count = db.execute("SELECT COUNT(*) FROM admin_alert_deliveries").fetchone()[0]
                if (alert_count + len(new_fingerprints) > _MAX_STORE_ROWS
                        or delivery_count + len(new_fingerprints) > _MAX_STORE_ROWS):
                    raise AdminAlertStoreCapacityError("alert state row limit reached")

                for fingerprint, (kind, status_group, payload) in prepared.items():
                    row = db.execute("SELECT episode_id, state FROM admin_alerts WHERE fingerprint=?",
                                     (fingerprint,)).fetchone()
                    if row is not None and row["state"] == "active":
                        db.execute("UPDATE admin_alerts SET last_seen=? WHERE fingerprint=?",
                                   (now, fingerprint))
                        continue

                    episode_id = secrets.token_hex(16)
                    if row is None:
                        db.execute("INSERT INTO admin_alerts(fingerprint, episode_id, kind, status_group, state, first_seen, last_seen) "
                                   "VALUES (?, ?, ?, ?, 'active', ?, ?)",
                                   (fingerprint, episode_id, kind, status_group, now, now))
                    else:
                        db.execute("UPDATE admin_alerts SET episode_id=?, kind=?, status_group=?, state='active', "
                                   "first_seen=?, last_seen=?, resolved_at=NULL WHERE fingerprint=?",
                                   (episode_id, kind, status_group, now, now, fingerprint))
                    db.execute("INSERT INTO admin_alert_deliveries "
                               "(id, fingerprint, episode_id, payload_json, state, next_at, created_at, updated_at) "
                               "VALUES (?, ?, ?, ?, 'pending', ?, ?, ?)",
                               (secrets.token_hex(16), fingerprint, episode_id, payload, now, now, now))
                    created += 1
                db.execute("COMMIT")
            except BaseException:
                db.execute("ROLLBACK")
                raise
        return created

    def claim(self, *, now=None, lease_seconds=60):
        """Lease the next due delivery. Expired leases become retryable."""
        now = _timestamp(now, "now")
        if (isinstance(lease_seconds, bool) or not isinstance(lease_seconds, (int, float))
                or not math.isfinite(lease_seconds) or lease_seconds <= 0):
            raise ValueError("lease_seconds must be positive and finite")

        with closing(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                db.execute("UPDATE admin_alert_deliveries SET state='failed', lease_token=NULL, lease_until=NULL, updated_at=? "
                           "WHERE state='leased' AND lease_until<=? AND attempts>=?",
                           (now, now, _MAX_ATTEMPTS))
                row = db.execute("SELECT * FROM admin_alert_deliveries WHERE attempts<? AND "
                                 "((state='pending' AND next_at<=?) OR (state='leased' AND lease_until<=?)) "
                                 "ORDER BY created_at, id LIMIT 1",
                                 (_MAX_ATTEMPTS, now, now)).fetchone()
                if row is None:
                    db.execute("COMMIT")
                    return None
                lease_token = secrets.token_urlsafe(24)
                db.execute("UPDATE admin_alert_deliveries SET state='leased', attempts=attempts+1, "
                           "lease_token=?, lease_until=?, updated_at=? WHERE id=?",
                           (lease_token, now + lease_seconds, now, row["id"]))
                db.execute("COMMIT")
                return {
                    "id": row["id"], "event_id": row["id"], "fingerprint": row["fingerprint"],
                    "episode_id": row["episode_id"], "payload": json.loads(row["payload_json"]),
                    "attempt": row["attempts"] + 1, "lease_token": lease_token,
                }
            except BaseException:
                db.execute("ROLLBACK")
                raise

    def finish(self, delivery_id, lease_token, *, delivered, retryable=True, now=None):
        """Complete a lease or schedule bounded exponential retry."""
        now = _timestamp(now, "now")
        if type(delivered) is not bool or type(retryable) is not bool:
            raise ValueError("delivered and retryable must be booleans")
        if not isinstance(delivery_id, str) or not isinstance(lease_token, str):
            raise ValueError("delivery id and lease token must be strings")

        with closing(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                row = db.execute("SELECT attempts FROM admin_alert_deliveries WHERE id=? AND state='leased' "
                                 "AND lease_token=? AND lease_until>?",
                                 (delivery_id, lease_token, now)).fetchone()
                if row is None:
                    db.execute("COMMIT")
                    return False
                if delivered:
                    db.execute("UPDATE admin_alert_deliveries SET state='delivered', delivered_at=?, updated_at=?, "
                               "lease_token=NULL, lease_until=NULL WHERE id=?",
                               (now, now, delivery_id))
                elif retryable and row["attempts"] < _MAX_ATTEMPTS:
                    delay = min(_BASE_RETRY_SECONDS * (2 ** (row["attempts"] - 1)), _MAX_RETRY_SECONDS)
                    db.execute("UPDATE admin_alert_deliveries SET state='pending', next_at=?, updated_at=?, "
                               "lease_token=NULL, lease_until=NULL WHERE id=?",
                               (now + delay, now, delivery_id))
                else:
                    db.execute("UPDATE admin_alert_deliveries SET state='failed', updated_at=?, "
                               "lease_token=NULL, lease_until=NULL WHERE id=?", (now, delivery_id))
                db.execute("COMMIT")
                return True
            except BaseException:
                db.execute("ROLLBACK")
                raise

    def prune(self, *, now=None, retention_seconds=_RETENTION_SECONDS):
        """Expire old terminal deliveries and resolved identities, retaining live work."""
        now = _timestamp(now, "now")
        if (isinstance(retention_seconds, bool) or not isinstance(retention_seconds, (int, float))
                or not math.isfinite(retention_seconds) or retention_seconds <= 0):
            raise ValueError("retention_seconds must be positive and finite")
        cutoff = now - retention_seconds
        with closing(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                removed = db.execute("DELETE FROM admin_alert_deliveries WHERE state IN ('delivered', 'failed', 'canceled') "
                                     "AND updated_at<?", (cutoff,)).rowcount
                db.execute("DELETE FROM admin_alerts WHERE state='resolved' AND resolved_at<? AND NOT EXISTS "
                           "(SELECT 1 FROM admin_alert_deliveries d WHERE d.fingerprint=admin_alerts.fingerprint "
                           "AND d.episode_id=admin_alerts.episode_id AND d.state IN ('pending', 'leased'))",
                           (cutoff,))
                db.execute("COMMIT")
                return removed
            except BaseException:
                db.execute("ROLLBACK")
                raise


class AdminAlertStoreCapacityError(ValueError):
    """Raised when bounded alert state cannot accept another query result."""
