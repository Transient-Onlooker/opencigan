from datetime import date, datetime, timedelta, timezone
from collections import Counter, OrderedDict
import logging
import re
import threading
import time
from backend.comcigan_proxy import configure_comcigan_proxy, with_comcigan_budget

_protocol = None
_protocol_expires = 0.0
_protocol_content = None
_protocol_lock = threading.Lock()
_verified_schools = OrderedDict()
logger = logging.getLogger("opensigan.timetable")


def _source_lesson_starts(day_time):
    if not isinstance(day_time, (list, tuple)):
        return {}
    starts = {}
    duplicates = set()
    for value in day_time:
        if not isinstance(value, str):
            continue
        match = re.fullmatch(r"\s*([1-9][0-9]?)\((\d{2}):(\d{2})\)\s*", value)
        if not match:
            continue
        period, hour, minute = map(int, match.groups())
        if period > 30 or hour > 23 or minute > 59:
            continue
        key = str(period)
        if key in starts:
            duplicates.add(key)
        else:
            starts[key] = f"{hour:02d}:{minute:02d}"
    for key in duplicates:
        starts.pop(key, None)
    return starts


def _search_with_cached_protocol(query, *, retry=True, with_protocol=False):
    configure_comcigan_proxy()
    from pycomcigan.helpers import get_comcigan_response_for_codes, school_search
    from pycomcigan.service_page import decode_service_page
    from pycomcigan.service_protocol import parse_service_protocol

    global _protocol, _protocol_expires, _protocol_content
    with _protocol_lock:
        now = time.monotonic()
        reused = _protocol is not None and now < _protocol_expires
        if not reused:
            _verified_schools.clear()
            _protocol_content = decode_service_page(get_comcigan_response_for_codes().text)
            _protocol = parse_service_protocol(_protocol_content)
            _protocol_expires = time.monotonic() + 300
        protocol = _protocol
    try:
        rows = school_search(query, protocol.endpoint, protocol)
        return (rows, protocol) if with_protocol else rows
    except RuntimeError as exc:
        message = str(exc)
        invalid_protocol = message in (
            'Encrypted response protocol mismatch',
            'Encrypted response authentication failed',
        )
        rejected = 'HTTP 403' in message
        if invalid_protocol or rejected:
            with _protocol_lock:
                if _protocol is protocol:
                    _protocol = None
                    _protocol_expires = 0.0
                    _protocol_content = None
                    _verified_schools.clear()
        if invalid_protocol and reused and retry:
            return _search_with_cached_protocol(query, retry=False, with_protocol=with_protocol)
        raise


@with_comcigan_budget
def search_schools(query):
    schools = []
    rows, searched_protocol = _search_with_cached_protocol(query, with_protocol=True)
    for row in rows:
        if (not isinstance(row, (list, tuple)) or len(row) < 4
                or not isinstance(row[3], int) or isinstance(row[3], bool) or row[3] <= 0
                or not isinstance(row[2], str) or not row[2] or len(row[2]) > 50
                or ":" in row[2] or not isinstance(row[1], str)):
            raise RuntimeError("학교 검색 응답 형식이 올바르지 않습니다")
        schools.append({"id": f"{row[3]}:{row[2]}", "name": row[2], "region": row[1]})
    counts = Counter(school["id"] for school in schools)
    code_counts = Counter(row[3] for row in rows)
    with _protocol_lock:
        if _protocol is not searched_protocol or _protocol_expires <= time.monotonic():
            return schools
        for school, row in zip(schools, rows):
            school_id = school["id"]
            _verified_schools.pop(school_id, None)
            if counts[school_id] == 1 and code_counts[row[3]] == 1 and type(row[0]) is int and row[0] >= 0:
                _verified_schools[school_id] = (row[0], time.monotonic() + 300)
                if len(_verified_schools) > 256:
                    _verified_schools.popitem(last=False)
    return schools


def validate_timetable_week(week):
    if not isinstance(week, str):
        raise ValueError("주 시작일이 올바르지 않습니다")
    try:
        start = date.fromisoformat(week)
    except ValueError:
        raise ValueError("주 시작일이 올바르지 않습니다") from None
    if start.isoformat() != week:
        raise ValueError("주 시작일이 올바르지 않습니다")
    today = datetime.now(timezone(timedelta(hours=9))).date()
    current = today - timedelta(days=today.weekday())
    offset = (start - current).days // 7
    if start.weekday() != 0 or offset not in (0, 1):
        raise ValueError("현재 주 또는 다음 주의 월요일을 선택하세요")
    return offset


@with_comcigan_budget
def fetch_timetable(school_id, week, *, include_original=False):
    global _protocol, _protocol_expires, _protocol_content
    configure_comcigan_proxy()
    from pycomcigan import TimeTable

    if not isinstance(school_id, str):
        raise ValueError("학교 식별자가 올바르지 않습니다")
    parts = school_id.split(":")
    if (len(parts) != 2 or not parts[0].isascii() or not parts[0].isdigit()
            or not parts[1] or len(parts[1]) > 50):
        raise ValueError("학교 식별자가 올바르지 않습니다")
    code, name = parts
    if int(code) == 0:
        raise ValueError("학교 식별자가 올바르지 않습니다")
    offset = validate_timetable_week(week)
    start = date.fromisoformat(week)
    try:
        with _protocol_lock:
            verified = _verified_schools.get(school_id)
            reusable = (verified and verified[1] > time.monotonic() and _protocol is not None
                        and _protocol_content is not None and _protocol_expires > time.monotonic())
            protocol, content = (_protocol, _protocol_content) if reusable else (None, None)
        if protocol is None:
            timetable = TimeTable(name, school_code=int(code), week_num=offset)
        else:
            codes = TimeTable._get_comcigan_codes(content)
            try:
                data = TimeTable._fetch_timetable_data(int(code), offset, codes, protocol)
            except RuntimeError as exc:
                invalid = str(exc) in ("Encrypted response protocol mismatch", "Encrypted response authentication failed")
                rejected = "HTTP 403" in str(exc)
                if not (invalid or rejected):
                    raise
                with _protocol_lock:
                    if _protocol is protocol:
                        _protocol = None
                        _protocol_expires = 0.0
                        _protocol_content = None
                        _verified_schools.clear()
                if rejected:
                    raise
                timetable = TimeTable(name, school_code=int(code), week_num=offset)
            else:
                timetable = TimeTable.__new__(TimeTable)
                timetable._initialize_from_data(data, verified[0], name, int(code), codes)
    except ValueError as exc:
        raise RuntimeError("시간표 제공자의 응답이 올바르지 않습니다") from exc
    normalization_started = time.monotonic()
    records = []
    data = timetable.timetable
    if not isinstance(data, (list, tuple)) or len(data) > 20:
        raise RuntimeError("시간표 응답 형식이 올바르지 않습니다")
    for grade, classes in enumerate(data):
        if (not isinstance(classes, (list, tuple)) or len(classes) > 100
                or (grade == 0 and classes)):
            raise RuntimeError("시간표 응답 형식이 올바르지 않습니다")
        for class_number, days in enumerate(classes):
            if (not isinstance(days, (list, tuple)) or len(days) > 8
                    or (class_number == 0 and days)):
                raise RuntimeError("시간표 응답 형식이 올바르지 않습니다")
            for day, lessons in enumerate(days):
                if day < 1 or day > 5:
                    continue
                if not isinstance(lessons, (list, tuple)) or len(lessons) > 30:
                    raise RuntimeError("시간표 응답 형식이 올바르지 않습니다")
                for lesson in lessons:
                    if (not isinstance(getattr(lesson, "subject", None), str)
                            or not isinstance(getattr(lesson, "teacher", None), str)
                            or not isinstance(getattr(lesson, "replaced", None), bool)
                            or not isinstance(getattr(lesson, "period", None), int)
                            or isinstance(lesson.period, bool) or lesson.period < 1):
                        raise RuntimeError("시간표 응답 형식이 올바르지 않습니다")
                    if not lesson.subject and not lesson.teacher and not lesson.replaced:
                        continue
                    record = {"grade": grade, "class": class_number,
                        "date": (start + timedelta(days=day - 1)).isoformat(),
                        "period": lesson.period, "subject": lesson.subject,
                        "teacher": lesson.teacher, "isChanged": lesson.replaced}
                    if include_original:
                        original = getattr(lesson, "original", None)
                        record["originalSubject"] = getattr(original, "subject", None)
                        record["originalTeacher"] = getattr(original, "teacher", None)
                    records.append(record)
    updated_at = None
    if timetable.update_date:
        try:
            updated = datetime.fromisoformat(str(timetable.update_date))
        except ValueError as exc:
            raise RuntimeError("시간표 갱신 시각이 올바르지 않습니다") from exc
        kst = timezone(timedelta(hours=9))
        updated_at = (updated.replace(tzinfo=kst) if updated.tzinfo is None
                      else updated.astimezone(kst)).isoformat()
    result = {"schoolId": school_id, "weekStart": week, "records": records,
        "sourceUpdatedAt": updated_at,
        "fetchedAt": datetime.now(timezone.utc).isoformat(), "stale": False}
    starts = _source_lesson_starts(getattr(timetable, "day_time", None))
    if starts:
        result["sourceLessonStarts"] = starts
    logger.info("timetable normalization duration_ms=%.1f", (time.monotonic() - normalization_started) * 1000)
    return result
