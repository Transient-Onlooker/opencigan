"""Create a calendar feed from cached timetable records."""

import hashlib
import re
from datetime import date, datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))
_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def _escape(value):
    return str(value).replace("\\", "\\\\").replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\\n").replace(";", "\\;").replace(",", "\\,")


def _fold(line):
    parts = []
    current = ""
    size = 0
    for char in line:
        width = len(char.encode("utf-8"))
        if size + width > 75:
            parts.append(current)
            current = " "
            size = 1
        current += char
        size += width
    parts.append(current)
    return parts


def _stamp(value):
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
    except (ValueError, AttributeError):
        parsed = datetime.now(timezone.utc)
    return parsed.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _normalize_lesson_times(lesson_times):
    if lesson_times is None:
        return {}
    if not isinstance(lesson_times, dict):
        raise ValueError("lesson_times는 dict여야 합니다")
    normalized = {}
    for period, entry in lesson_times.items():
        if not isinstance(period, int) or isinstance(period, bool) or period < 1 or period > 20:
            raise ValueError(f"교시 번호는 1에서 20 사이의 정수여야 합니다: {period}")
        if not isinstance(entry, dict):
            raise ValueError(f"{period}교시 시간 설정 형식이 올바르지 않습니다")
        start_raw = entry.get("start")
        end_raw = entry.get("end")
        if not isinstance(start_raw, str) or not isinstance(end_raw, str):
            raise ValueError(f"{period}교시 시작/종료 시각은 문자열이어야 합니다")
        if not _TIME_RE.match(start_raw) or not _TIME_RE.match(end_raw):
            raise ValueError(f"{period}교시 시각 형식은 HH:MM이어야 합니다")
        sh, sm = int(start_raw[:2]), int(start_raw[3:5])
        eh, em = int(end_raw[:2]), int(end_raw[3:5])
        if (sh, sm) >= (eh, em):
            raise ValueError(f"{period}교시 시작 시각이 종료 시각보다 앞서야 합니다")
        normalized[period] = ((sh, sm), (eh, em))
    return normalized


def render_timetable_ics(school, grade, classroom, timetables, mode="periods", lesson_times=None):
    name = school.split(":", 1)[1] if ":" in school else school
    lines = [
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Opencigan//Timetable//KO",
        "CALSCALE:GREGORIAN", "METHOD:PUBLISH",
        "X-WR-CALNAME:" + _escape(f"{name} {grade}학년 {classroom}반"),
        "REFRESH-INTERVAL;VALUE=DURATION:PT30M",
    ]
    normalized_times = _normalize_lesson_times(lesson_times) if mode == "timed" else {}

    for timetable in timetables:
        timestamp = _stamp(timetable.get("sourceUpdatedAt") or timetable.get("fetchedAt"))
        if mode == "summary":
            days = {}
            for record in timetable.get("records", []):
                if int(record["grade"]) != grade or int(record["class"]) != classroom:
                    continue
                day = date.fromisoformat(record["date"])
                days.setdefault(day, []).append(record)
            for day, records in sorted(days.items()):
                identity = f"{school}|{grade}|{classroom}|{day.isoformat()}|summary"
                uid = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:32] + "@opencigan"
                sorted_records = sorted(
                    records,
                    key=lambda r: (
                        int(r["period"]),
                        str(r.get("subject") or ""),
                        str(r.get("teacher") or ""),
                        bool(r.get("isChanged")),
                    ),
                )
                details = []
                for record in sorted_records:
                    item = f"{int(record['period'])}교시 {record.get('subject') or '수업'}"
                    if record.get("teacher"):
                        item += f" · {record['teacher']}"
                    if record.get("isChanged"):
                        item += " (변경)"
                    details.append(item)
                lines.extend([
                    "BEGIN:VEVENT", "UID:" + uid, "DTSTAMP:" + timestamp,
                    "DTSTART;VALUE=DATE:" + day.strftime("%Y%m%d"),
                    "DTEND;VALUE=DATE:" + (day + timedelta(days=1)).strftime("%Y%m%d"),
                    "SUMMARY:" + _escape(f"{name} {grade}학년 {classroom}반 · {len(sorted_records)}개 수업"),
                    "DESCRIPTION:" + _escape("\n".join(details)), "END:VEVENT",
                ])
            continue

        period_groups = {}
        for record in timetable.get("records", []):
            if int(record["grade"]) != grade or int(record["class"]) != classroom:
                continue
            day = date.fromisoformat(record["date"])
            period = int(record["period"])
            period_groups.setdefault((day, period), []).append(record)

        for (day, period), group in sorted(period_groups.items(), key=lambda item: item[0]):
            sorted_records = (
                group if len(group) == 1
                else sorted(
                    group,
                    key=lambda r: (
                        str(r.get("subject") or ""),
                        str(r.get("teacher") or ""),
                        bool(r.get("isChanged")),
                        repr(sorted((str(k), str(v)) for k, v in r.items())),
                    ),
                )
            )
            for idx, record in enumerate(sorted_records):
                if len(group) == 1:
                    identity = f"{school}|{grade}|{classroom}|{day.isoformat()}|{period}"
                else:
                    identity = f"{school}|{grade}|{classroom}|{day.isoformat()}|{period}|{idx}"
                uid = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:32] + "@opencigan"
                subject = record.get("subject") or "수업"
                details = [f"{period}교시"]

                has_time = False
                dtstart_line = None
                dtend_line = None
                if mode == "timed" and period in normalized_times:
                    (sh, sm), (eh, em) = normalized_times[period]
                    start_dt = datetime(day.year, day.month, day.day, sh, sm, tzinfo=KST).astimezone(timezone.utc)
                    end_dt = datetime(day.year, day.month, day.day, eh, em, tzinfo=KST).astimezone(timezone.utc)
                    dtstart_line = "DTSTART:" + start_dt.strftime("%Y%m%dT%H%M%SZ")
                    dtend_line = "DTEND:" + end_dt.strftime("%Y%m%dT%H%M%SZ")
                    has_time = True

                if not has_time:
                    dtstart_line = "DTSTART;VALUE=DATE:" + day.strftime("%Y%m%d")
                    dtend_line = "DTEND;VALUE=DATE:" + (day + timedelta(days=1)).strftime("%Y%m%d")
                    if mode == "timed":
                        details.append("교시 시각 미설정")

                if record.get("teacher"):
                    details.append(f"교사: {record['teacher']}")
                if record.get("isChanged"):
                    details.append("변경된 수업")

                lines.extend([
                    "BEGIN:VEVENT", "UID:" + uid, "DTSTAMP:" + timestamp,
                    dtstart_line, dtend_line,
                    "SUMMARY:" + _escape(f"{period}교시 {subject}"),
                    "DESCRIPTION:" + _escape("\n".join(details)), "END:VEVENT",
                ])
    lines.append("END:VCALENDAR")
    return ("\r\n".join(part for line in lines for part in _fold(line)) + "\r\n").encode("utf-8")
