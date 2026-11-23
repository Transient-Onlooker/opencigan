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
           max_error_ratio: float, max_distinct_schools: int, min_requests: int = 0):
    """Group recent access-log rows per client IP and flag configured patterns.

    Thresholds are caller-supplied so the review can be exercised in tests
    without touching real traffic or production thresholds.
    """
    rows = db.execute(
        "SELECT timestamp, client_ip, route, status, school_id FROM access_logs "
        "WHERE timestamp >= ?", (_cutoff_iso(window_hours),)).fetchall()
    grouped = {}
    for row in rows:
        grouped.setdefault(row["client_ip"], []).append(row)

    findings = []
    for client_ip, entries in sorted(grouped.items()):
        count = len(entries)
        errors = sum(1 for entry in entries if int(entry["status"]) >= 400)
        schools = {entry["school_id"] for entry in entries if entry["school_id"]}
        error_ratio = (errors / count) if count else 0.0
        if count > max_requests_per_ip and count >= min_requests:
            findings.append({
                "client_ip": client_ip, "kind": "request_volume", "observed": count,
                "threshold": max_requests_per_ip, "errors": errors,
                "error_ratio": round(error_ratio, 4), "distinct_schools": len(schools),
                "first_seen": entries[0]["timestamp"], "last_seen": entries[-1]["timestamp"],
                "detail": "요청 수가 검토 기준을 넘음",
            })
        if count >= min_requests and error_ratio > max_error_ratio:
            findings.append({
                "client_ip": client_ip, "kind": "error_ratio", "observed": round(error_ratio, 4),
                "threshold": max_error_ratio, "errors": errors, "requests": count,
                "distinct_schools": len(schools),
                "first_seen": entries[0]["timestamp"], "last_seen": entries[-1]["timestamp"],
                "detail": "오류 응답 비율이 검토 기준을 넘음",
            })
        if len(schools) > max_distinct_schools and count >= min_requests:
            findings.append({
                "client_ip": client_ip, "kind": "school_scan", "observed": len(schools),
                "threshold": max_distinct_schools, "requests": count, "errors": errors,
                "error_ratio": round(error_ratio, 4),
                "first_seen": entries[0]["timestamp"], "last_seen": entries[-1]["timestamp"],
                "detail": "검토 구간에서 조회된 학교 수가 많음",
            })
    return findings
