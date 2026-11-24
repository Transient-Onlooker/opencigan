"""Access log storage, asynchronous recording, query filtering, and safe CSV export."""

import csv
import io
import logging
import os
import re
import sqlite3
import threading
import uuid
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from queue import Empty, Full, Queue
from typing import Any, Dict, Iterable, List, Optional, Tuple, Union
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

try:
    SEOUL = ZoneInfo("Asia/Seoul")
except ZoneInfoNotFoundError:
    SEOUL = timezone(timedelta(hours=9), name="Asia/Seoul")

LOGGER = logging.getLogger("opensigan.access_logs")

FORMULA_CONTROL_PREFIXES = ("\t", "\r")
FORMULA_OPERATOR_PREFIXES = ("=", "+", "-", "@")
DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def get_access_log_store(retention_days: int = 7) -> Optional["AccessLogStore"]:
    """Return an AccessLogStore instance if OPENCIGAN_ACCESS_LOG_DB is configured, else None."""
    db_path = os.environ.get("OPENCIGAN_ACCESS_LOG_DB", "").strip()
    if not db_path:
        return None
    return AccessLogStore(db_path, retention_days=retention_days)


def normalize_origin(raw: Optional[str]) -> str:
    """Extract scheme and hostname[:port] only.

    Strips credentials, paths, query strings, and fragments.
    """
    if not raw or not isinstance(raw, str):
        return ""
    cleaned = raw.strip()
    if not cleaned:
        return ""
    try:
        parsed = urlparse(cleaned)
        scheme = parsed.scheme.lower()
        if scheme not in ("http", "https"):
            return ""
        hostname = parsed.hostname
        if not hostname:
            return ""
        if parsed.port:
            return f"{scheme}://{hostname}:{parsed.port}"
        return f"{scheme}://{hostname}"
    except (ValueError, TypeError):
        return ""


def classify_origin(
    origin_header: Optional[str],
    referer_header: Optional[str],
    allowed_origins: Optional[Union[str, Iterable[str]]] = None,
) -> Tuple[str, str]:
    """Classify origin into 'frontend', 'external', or 'unknown'.

    Note: Origin and Referer headers are telemetry signals only and must not
    be used for authentication or authorization.
    """
    extracted = normalize_origin(origin_header) or normalize_origin(referer_header)
    if not extracted:
        return "unknown", ""

    allowed: List[str] = []
    if allowed_origins:
        if isinstance(allowed_origins, str):
            allowed = [normalize_origin(o) for o in allowed_origins.split(",") if o.strip()]
        else:
            allowed = [normalize_origin(o) for o in allowed_origins if o]
    allowed = [a for a in allowed if a]

    if allowed and extracted in allowed:
        return "frontend", extracted
    return "external", extracted


def csv_safe_cell(value: Any) -> Any:
    """Escape spreadsheet formula triggers to prevent CSV injection (CWE-1236)."""
    if value is None:
        return ""
    text_val = str(value)
    if not text_val:
        return ""
    if text_val[0] in FORMULA_CONTROL_PREFIXES:
        return f"'{text_val}"
    stripped = text_val.lstrip()
    if stripped and stripped[0] in FORMULA_OPERATOR_PREFIXES:
        return f"'{text_val}"
    return text_val


def parse_kst_timestamp(received_at: Optional[Union[datetime, str]] = None) -> Tuple[str, str]:
    """Validate and convert receipt timestamp to KST (timestamp_iso, day_str).

    Rejects naive datetimes and malformed timestamp strings.
    Defaults to current KST time when received_at is None.
    """
    if received_at is None:
        now_dt = datetime.now(SEOUL)
        return now_dt.isoformat(), now_dt.date().isoformat()

    if isinstance(received_at, datetime):
        if received_at.tzinfo is None:
            raise ValueError("received_at datetime must be timezone-aware")
        dt_kst = received_at.astimezone(SEOUL)
        return dt_kst.isoformat(), dt_kst.date().isoformat()

    if isinstance(received_at, str):
        cleaned = received_at.strip()
        try:
            dt = datetime.fromisoformat(cleaned.replace("Z", "+00:00"))
        except (ValueError, TypeError) as exc:
            raise ValueError(f"invalid received_at timestamp string: {cleaned!r}") from exc
        if dt.tzinfo is None:
            raise ValueError("received_at string must include a timezone offset")
        dt_kst = dt.astimezone(SEOUL)
        return dt_kst.isoformat(), dt_kst.date().isoformat()

    raise TypeError("received_at must be an aware datetime, an ISO string, or None")


class AccessLogStore:
    """SQLite store for operational access logs with automatic retention."""

    def __init__(self, path: Union[str, Path] = ":memory:", retention_days: int = 7):
        if retention_days < 1:
            raise ValueError("retention_days must be at least 1")
        self.path = str(path)
        self.retention_days = int(retention_days)
        self._memory_uri = None
        self._memory_anchor = None
        self._purge_lock = threading.Lock()
        self._last_purge_day = None

        if self.path == ":memory:":
            self._memory_uri = f"file:opensigan-access-{uuid.uuid4().hex}?mode=memory&cache=shared"
            self._memory_anchor = sqlite3.connect(self._memory_uri, uri=True)
        else:
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)

        with closing(self._connect()) as db:
            if self.path != ":memory:":
                db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS access_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    day TEXT NOT NULL,
                    client_ip TEXT NOT NULL,
                    method TEXT NOT NULL,
                    route TEXT NOT NULL,
                    school_id TEXT,
                    grade TEXT,
                    class_nm TEXT,
                    week TEXT,
                    dates TEXT,
                    datatype TEXT,
                    status INTEGER NOT NULL,
                    duration_ms REAL NOT NULL,
                    cache_status TEXT,
                    referrer_origin TEXT,
                    origin_class TEXT NOT NULL,
                    user_agent TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_access_logs_day ON access_logs(day);
                CREATE INDEX IF NOT EXISTS idx_access_logs_client_ip ON access_logs(client_ip);
                CREATE INDEX IF NOT EXISTS idx_access_logs_school_id ON access_logs(school_id);
                CREATE INDEX IF NOT EXISTS idx_access_logs_route ON access_logs(route);
                CREATE INDEX IF NOT EXISTS idx_access_logs_status ON access_logs(status);
                CREATE INDEX IF NOT EXISTS idx_access_logs_origin_class ON access_logs(origin_class);
            """)
            existing_columns = {
                row[1] for row in db.execute("PRAGMA table_info(access_logs)").fetchall()
            }
            if "user_agent" not in existing_columns:
                db.execute("ALTER TABLE access_logs ADD COLUMN user_agent TEXT")
            self._purge_if_due(db, self._current_day())
            db.commit()

    def _connect(self) -> sqlite3.Connection:
        db = (
            sqlite3.connect(self._memory_uri, uri=True, timeout=0.1)
            if self._memory_uri
            else sqlite3.connect(self.path, timeout=0.1)
        )
        db.row_factory = sqlite3.Row
        return db

    @staticmethod
    def _current_day() -> str:
        return datetime.now(SEOUL).date().isoformat()

    def _purge_if_due(self, db: sqlite3.Connection, today: str) -> None:
        with self._purge_lock:
            if self._last_purge_day == today:
                return
            cutoff = (
                datetime.fromisoformat(today).date() - timedelta(days=self.retention_days - 1)
            ).isoformat()
            db.execute("DELETE FROM access_logs WHERE day < ?", (cutoff,))
            db.commit()
            self._last_purge_day = today

    def sanitize_event(
        self,
        raw_event: Dict[str, Any],
        *,
        received_at: Optional[Union[datetime, str]] = None,
    ) -> Dict[str, Any]:
        """Keep only whitelisted operational fields and normalize values."""
        timestamp, day = parse_kst_timestamp(received_at)

        raw_route = str(raw_event.get("route") or raw_event.get("path") or "/").strip()
        try:
            parsed = urlparse(raw_route)
            route_path = parsed.path if parsed.path else raw_route
        except Exception:
            route_path = raw_route
        if "?" in route_path:
            route_path = route_path.split("?", 1)[0]
        if "#" in route_path:
            route_path = route_path.split("#", 1)[0]
        route_path = route_path.strip()
        if not route_path.startswith("/"):
            route_path = f"/{route_path}"
        route = route_path[:255]

        client_ip = str(raw_event.get("client_ip") or raw_event.get("ip") or "").strip()[:64]
        if not client_ip:
            client_ip = "unknown"

        method = str(raw_event.get("method") or "GET").strip().upper()[:16]

        try:
            status = int(raw_event.get("status", 200))
        except (ValueError, TypeError):
            status = 200

        try:
            duration_ms = max(0.0, float(raw_event.get("duration_ms", 0.0)))
        except (ValueError, TypeError):
            duration_ms = 0.0

        origin_class = str(raw_event.get("origin_class") or "").strip().lower()
        if origin_class not in ("frontend", "external", "unknown"):
            origin_class = "unknown"

        referrer_origin = normalize_origin(raw_event.get("referrer_origin"))[:255]

        def opt_str(key: str, max_len: int = 64) -> Optional[str]:
            val = raw_event.get(key)
            if val is None:
                return None
            s = str(val).strip()
            return s[:max_len] if s else None

        return {
            "timestamp": timestamp,
            "day": day,
            "client_ip": client_ip,
            "method": method,
            "route": route,
            "school_id": opt_str("school_id", 100),
            "grade": opt_str("grade", 16),
            "class_nm": opt_str("class_nm", 16) or opt_str("class", 16),
            "week": opt_str("week", 32),
            "dates": opt_str("dates", 32),
            "datatype": opt_str("datatype", 32) or opt_str("data_type", 32),
            "status": status,
            "duration_ms": round(duration_ms, 2),
            "cache_status": opt_str("cache_status", 16),
            "referrer_origin": referrer_origin,
            "origin_class": origin_class,
            "user_agent": opt_str("user_agent", 300),
        }

    def record(
        self,
        event: Dict[str, Any],
        *,
        received_at: Optional[Union[datetime, str]] = None,
    ) -> int:
        """Sanitize and record an access log entry with trusted receipt timestamp."""
        sanitized = self.sanitize_event(event, received_at=received_at)
        today = self._current_day()
        with closing(self._connect()) as db:
            self._purge_if_due(db, today)
            cursor = db.execute(
                """
                INSERT INTO access_logs (
                    timestamp, day, client_ip, method, route, school_id, grade,
                    class_nm, week, dates, datatype, status, duration_ms,
                    cache_status, referrer_origin, origin_class, user_agent
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    sanitized["timestamp"],
                    sanitized["day"],
                    sanitized["client_ip"],
                    sanitized["method"],
                    sanitized["route"],
                    sanitized["school_id"],
                    sanitized["grade"],
                    sanitized["class_nm"],
                    sanitized["week"],
                    sanitized["dates"],
                    sanitized["datatype"],
                    sanitized["status"],
                    sanitized["duration_ms"],
                    sanitized["cache_status"],
                    sanitized["referrer_origin"],
                    sanitized["origin_class"],
                    sanitized["user_agent"],
                ),
            )
            db.commit()
            return cursor.lastrowid

    def query(
        self,
        filters: Optional[Dict[str, Any]] = None,
        cursor: Optional[Union[str, int]] = None,
        limit: int = 50,
    ) -> Dict[str, Any]:
        """Query access logs using cursor-based pagination and parameterized SQL."""
        try:
            limit = max(1, min(int(limit), 100))
        except (ValueError, TypeError):
            limit = 50

        filters = filters or {}
        conditions = []
        params: List[Any] = []

        if cursor is not None:
            try:
                cursor_id = int(cursor)
                if cursor_id < 1:
                    raise ValueError
                conditions.append("id < ?")
                params.append(cursor_id)
            except (ValueError, TypeError):
                raise ValueError("invalid cursor: must be a positive integer ID")

        if filters.get("client_ip"):
            conditions.append("client_ip = ?")
            params.append(str(filters["client_ip"]).strip())

        if filters.get("school_id"):
            conditions.append("school_id = ?")
            params.append(str(filters["school_id"]).strip())

        if filters.get("grade") is not None:
            conditions.append("grade = ?")
            params.append(str(filters["grade"]).strip())

        if filters.get("class_nm") is not None or filters.get("class") is not None:
            cls_val = filters.get("class_nm") if filters.get("class_nm") is not None else filters.get("class")
            conditions.append("class_nm = ?")
            params.append(str(cls_val).strip())

        if filters.get("start_day"):
            start_val = str(filters["start_day"]).strip()
            if not DATE_PATTERN.match(start_val):
                raise ValueError("invalid start_day: expected YYYY-MM-DD")
            conditions.append("day >= ?")
            params.append(start_val)

        if filters.get("end_day"):
            end_val = str(filters["end_day"]).strip()
            if not DATE_PATTERN.match(end_val):
                raise ValueError("invalid end_day: expected YYYY-MM-DD")
            conditions.append("day <= ?")
            params.append(end_val)

        if filters.get("route"):
            conditions.append("route = ?")
            params.append(str(filters["route"]).strip())

        if filters.get("status") is not None:
            try:
                st = int(filters["status"])
                if not (100 <= st <= 599):
                    raise ValueError
                conditions.append("status = ?")
                params.append(st)
            except (ValueError, TypeError):
                raise ValueError("invalid status: must be an HTTP status code (100-599)")

        if filters.get("min_status") is not None:
            try:
                mst = int(filters["min_status"])
                if not (100 <= mst <= 599):
                    raise ValueError
                conditions.append("status >= ?")
                params.append(mst)
            except (ValueError, TypeError):
                raise ValueError("invalid min_status: must be an HTTP status code (100-599)")

        if filters.get("origin_class"):
            oc = str(filters["origin_class"]).strip().lower()
            if oc not in ("frontend", "external", "unknown"):
                raise ValueError("invalid origin_class: must be frontend, external, or unknown")
            conditions.append("origin_class = ?")
            params.append(oc)

        if filters.get("cache_status"):
            conditions.append("cache_status = ?")
            params.append(str(filters["cache_status"]).strip().upper())

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        sql = f"SELECT * FROM access_logs {where_clause} ORDER BY id DESC LIMIT ?"
        params.append(limit + 1)

        today = self._current_day()
        with closing(self._connect()) as db:
            self._purge_if_due(db, today)
            rows = [dict(r) for r in db.execute(sql, params).fetchall()]

        has_more = len(rows) > limit
        items = rows[:limit]
        next_cursor = str(items[-1]["id"]) if (has_more and items) else None

        return {
            "items": items,
            "next_cursor": next_cursor,
            "limit": limit,
            "has_more": has_more,
        }

    def review_anomalies(self, *, window_hours: int, max_requests_per_ip: int,
                         max_error_ratio: float, max_distinct_schools: int,
                         min_requests: int = 0) -> List[Dict[str, Any]]:
        """Review retained logs using the same lifecycle as ordinary queries."""
        from backend.query_anomalies import detect

        today = self._current_day()
        earliest_day = (
            date.fromisoformat(today) - timedelta(days=self.retention_days - 1)
        ).isoformat()
        with closing(self._connect()) as db:
            self._purge_if_due(db, today)
            return detect(
                db, window_hours=window_hours,
                max_requests_per_ip=max_requests_per_ip,
                max_error_ratio=max_error_ratio,
                max_distinct_schools=max_distinct_schools,
                min_requests=min_requests, earliest_day=earliest_day,
            )

    def export_csv(
        self,
        filters: Optional[Dict[str, Any]] = None,
        limit: int = 1000,
    ) -> str:
        """Export queried logs to safe CSV format with formula injection escaping."""
        finite_limit = max(1, min(int(limit), 5000))
        res = self.query(filters=filters, cursor=None, limit=min(finite_limit, 100))
        rows = list(res["items"])
        cursor = res["next_cursor"]

        while cursor and len(rows) < finite_limit:
            remaining = finite_limit - len(rows)
            page_limit = min(remaining, 100)
            next_res = self.query(filters=filters, cursor=cursor, limit=page_limit)
            rows.extend(next_res["items"])
            cursor = next_res["next_cursor"]
            if not next_res["has_more"]:
                break

        fields = [
            "id",
            "timestamp",
            "day",
            "client_ip",
            "method",
            "route",
            "school_id",
            "grade",
            "class_nm",
            "week",
            "dates",
            "datatype",
            "status",
            "duration_ms",
            "cache_status",
            "referrer_origin",
            "origin_class",
            "user_agent",
        ]

        output = io.StringIO()
        writer = csv.writer(output, quoting=csv.QUOTE_MINIMAL)
        writer.writerow(fields)
        for r in rows:
            escaped_row = [csv_safe_cell(r.get(f)) for f in fields]
            writer.writerow(escaped_row)
        return output.getvalue()

    def close(self) -> None:
        """Close in-memory anchor connection if active."""
        if self._memory_anchor is not None:
            try:
                self._memory_anchor.close()
            except Exception:
                pass
            self._memory_anchor = None


class AccessLogRecorder:
    """Thread-safe bounded asynchronous worker queue for recording access logs."""

    def __init__(self, store_factory, capacity: int = 1024):
        self.queue: Queue = Queue(maxsize=capacity)
        self.store_factory = store_factory
        self.dropped = 0
        self._start_lock = threading.Lock()
        self._drain_cond = threading.Condition(self._start_lock)
        self._worker: Optional[threading.Thread] = None
        self._closed = False

    def submit(
        self,
        event: Dict[str, Any],
        *,
        received_at: Optional[Union[datetime, str]] = None,
    ) -> bool:
        """Non-blocking submission of access log event to asynchronous queue.

        Captures contact timestamp prior to enqueueing.
        """
        if self._closed:
            return False

        if received_at is None:
            received_at = datetime.now(SEOUL)

        with self._start_lock:
            if self._closed:
                return False
            if self._worker is None:
                self._worker = threading.Thread(
                    target=self._run, name="access-log-writer", daemon=True
                )
                self._worker.start()

            try:
                self.queue.put_nowait((event, received_at))
                return True
            except Full:
                self.dropped += 1
                return False

    def _run(self) -> None:
        while True:
            try:
                item = self.queue.get(timeout=0.1)
            except Empty:
                with self._start_lock:
                    if self._closed:
                        return
                continue
            event, received_at = item
            try:
                store = self.store_factory()
                if store is not None:
                    store.record(event, received_at=received_at)
            except Exception:
                self.dropped += 1
                LOGGER.warning("access log event could not be recorded", exc_info=False)
            finally:
                self.queue.task_done()
                with self._drain_cond:
                    self._drain_cond.notify_all()

    def flush(self, timeout: Optional[float] = None) -> bool:
        """Wait for the recorder queue to finish processing pending events with optional timeout."""
        with self._drain_cond:
            if self.queue.unfinished_tasks == 0:
                return True
            return self._drain_cond.wait_for(lambda: self.queue.unfinished_tasks == 0, timeout=timeout)

    def close(self, timeout: float = 2.0) -> bool:
        """Signal worker thread to exit and close queue with bounded timeout."""
        with self._start_lock:
            self._closed = True
            worker = self._worker

        if worker is not None and worker.is_alive():
            worker.join(timeout=timeout)
            with self._start_lock:
                if not worker.is_alive():
                    self._worker = None
                    return True
                return False
        return True

