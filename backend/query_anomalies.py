"""Read-only review of unusually patterned traffic in the access log.

This is an offline review aid, not a blocking or alerting path: nothing here
rejects requests or triggers notifications. Findings are grouped so that no
individual request sequence is reconstructed beyond what access_logs already
stores for operators.
"""

from datetime import datetime, timedelta, timezone

SEOUL = timezone(timedelta(hours=9))
DEFAULT_WINDOW_HOURS = 24
DEFAULT_MAX_REQUESTS_PER_IP = 1000
DEFAULT_MAX_ERROR_RATIO = 0.5
DEFAULT_MAX_DISTINCT_SCHOOLS = 50
DEFAULT_MIN_REQUESTS = 20


def _cutoff_iso(window_hours: int) -> str:
    cutoff = datetime.now(tz=SEOUL) - timedelta(hours=window_hours)
    return cutoff.isoformat()


def detect(db, *, window_hours: int, max_requests_per_ip: int,
           max_error_ratio: float, max_distinct_schools: int, min_requests: int = 0,
           earliest_day: str = "", max_status_errors: int | None = None):
    """Group recent access-log rows per client IP and flag configured patterns.

    Thresholds are caller-supplied so the review can be exercised in tests
    without touching real traffic or production thresholds.
    """
    cutoff = _cutoff_iso(window_hours)
    # Stored timestamps are normalized to KST. Removing the fixed offset
    # before comparison also sorts whole seconds before fractional seconds.
    # Aggregate in SQLite rather than loading every request into Python.
    rows = db.execute(
        """
        SELECT client_ip, COUNT(*) AS requests,
               SUM(CASE WHEN status >= 400 THEN 1 ELSE 0 END) AS errors,
               SUM(CASE WHEN status = 404 THEN 1 ELSE 0 END) AS errors_404,
               SUM(CASE WHEN status = 429 THEN 1 ELSE 0 END) AS errors_429,
               SUM(CASE WHEN status >= 500 AND status < 600 THEN 1 ELSE 0 END) AS errors_5xx,
               COUNT(DISTINCT NULLIF(school_id, '')) AS distinct_schools,
               MIN(substr(timestamp, 1, length(timestamp) - 6)) || '+09:00' AS first_seen,
               MAX(substr(timestamp, 1, length(timestamp) - 6)) || '+09:00' AS last_seen
        FROM access_logs
        WHERE day >= ?
          AND substr(timestamp, 1, length(timestamp) - 6) >= ?
          AND client_ip NOT IN ('', 'unknown')
        GROUP BY client_ip
        HAVING COUNT(*) >= ?
        ORDER BY client_ip
        """, (max(cutoff[:10], earliest_day), cutoff[:-6], min_requests))

    findings = []
    for row in rows:
        client_ip = row["client_ip"]
        count = row["requests"]
        errors = row["errors"]
        distinct_schools = row["distinct_schools"]
        error_ratio = errors / count
        if max_status_errors is not None:
            for category in ("404", "429", "5xx"):
                observed = row[f"errors_{category}"]
                if observed > max_status_errors:
                    findings.append({
                        "client_ip": client_ip, "kind": "status_errors", "status_group": category,
                        "observed": observed, "threshold": max_status_errors, "requests": count,
                        "first_seen": row["first_seen"], "last_seen": row["last_seen"],
                        "detail": "상태별 오류 수가 검토 기준을 넘음",
                    })
        if count > max_requests_per_ip and count >= min_requests:
            findings.append({
                "client_ip": client_ip, "kind": "request_volume", "observed": count,
                "threshold": max_requests_per_ip, "errors": errors,
                "error_ratio": round(error_ratio, 4), "distinct_schools": distinct_schools,
                "first_seen": row["first_seen"], "last_seen": row["last_seen"],
                "detail": "요청 수가 검토 기준을 넘음",
            })
        if count >= min_requests and error_ratio > max_error_ratio:
            findings.append({
                "client_ip": client_ip, "kind": "error_ratio", "observed": round(error_ratio, 4),
                "threshold": max_error_ratio, "errors": errors, "requests": count,
                "distinct_schools": distinct_schools,
                "first_seen": row["first_seen"], "last_seen": row["last_seen"],
                "detail": "오류 응답 비율이 검토 기준을 넘음",
            })
        if distinct_schools > max_distinct_schools and count >= min_requests:
            findings.append({
                "client_ip": client_ip, "kind": "school_scan", "observed": distinct_schools,
                "threshold": max_distinct_schools, "requests": count, "errors": errors,
                "error_ratio": round(error_ratio, 4),
                "first_seen": row["first_seen"], "last_seen": row["last_seen"],
                "detail": "검토 구간에서 조회된 학교 수가 많음",
            })
    return findings
