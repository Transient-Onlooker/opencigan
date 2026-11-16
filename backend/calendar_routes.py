import hashlib
import re
from datetime import datetime, timedelta, timezone


def timetable_calendar(query, current_cache, request_headers, headers, query_param, timetable_filters, cached_timetable, render_ics):
    school = query_param(query, "school", 100)
    if not re.fullmatch(r"[0-9]+:[^:]{1,50}", school):
        raise ValueError("학교 식별자가 올바르지 않습니다")
    grade_filter, class_filter, teacher_filter = timetable_filters(query, require_class=True)
    weeks = query_param(query, "weeks", 1) if "weeks" in query else "1"
    if weeks not in ("1", "2"):
        raise ValueError("weeks는 1 또는 2여야 합니다")
    mode = query_param(query, "mode", 10) if "mode" in query else "periods"
    if mode not in ("periods", "summary", "timed"):
        raise ValueError("mode는 periods, summary 또는 timed여야 합니다")
    lesson_times = {}
    weekday_times = {}
    if "times" in query:
        if mode != "timed":
            raise ValueError("교시 시각은 timed 모드에서만 사용할 수 있습니다")
        raw_times = query_param(query, "times", 400)
        for item in raw_times.split(","):
            match = re.fullmatch(r"([1-9]|1[0-9]|20):([0-2][0-9][0-5][0-9])-([0-2][0-9][0-5][0-9])", item)
            if not match:
                raise ValueError("교시 시각 형식은 1:0900-0950입니다")
            period = int(match[1])
            start = match[2][:2] + ":" + match[2][2:]
            end = match[3][:2] + ":" + match[3][2:]
            if period in lesson_times or start >= end or end > "23:59":
                raise ValueError("교시 시각의 중복·범위·순서를 확인하세요")
            lesson_times[period] = {"start": start, "end": end}
        ordered = [value for _, value in sorted(lesson_times.items())]
        if any(value["start"] < ordered[index - 1]["end"] for index, value in enumerate(ordered) if index):
            raise ValueError("교시 시각이 겹칩니다")
    if "weekday_times" in query:
        if mode != "timed":
            raise ValueError("요일별 시각은 timed 모드에서만 사용할 수 있습니다")
        raw_overrides = query_param(query, "weekday_times", 2400)
        for item in raw_overrides.split(","):
            match = re.fullmatch(r"([1-7])\.([1-9]|1[0-9]|20):([0-2][0-9][0-5][0-9])-([0-2][0-9][0-5][0-9])", item)
            if not match:
                raise ValueError("요일별 시각 형식은 1.1:0900-0950입니다")
            weekday, period = int(match[1]), int(match[2])
            start = match[3][:2] + ":" + match[3][2:]
            end = match[4][:2] + ":" + match[4][2:]
            entries = weekday_times.setdefault(weekday, {})
            if period in entries or start >= end or end > "23:59":
                raise ValueError("요일별 시각의 중복·범위·순서를 확인하세요")
            entries[period] = {"start": start, "end": end}
        for entries in weekday_times.values():
            merged = {**lesson_times, **entries}
            ordered = [value for _, value in sorted(merged.items())]
            if any(value["start"] < ordered[index - 1]["end"] for index, value in enumerate(ordered) if index):
                raise ValueError("요일별 교시 시각이 겹칩니다")
    now = datetime.now(timezone(timedelta(hours=9))).date()
    monday = now - timedelta(days=now.weekday())
    timetables = []
    for offset in range(int(weeks)):
        week = (monday + timedelta(days=offset * 7)).isoformat()
        timetable, _ = cached_timetable(school, week, current_cache)
        if teacher_filter is not None:
            timetable = {**timetable, "records": [r for r in timetable["records"]
                         if teacher_filter in (r.get("teacher") or "").casefold()]}
        timetables.append(timetable)
    if weekday_times:
        body = render_ics(school, grade_filter, class_filter, timetables, mode=mode, lesson_times=lesson_times, weekday_times=weekday_times)
    else:
        body = render_ics(school, grade_filter, class_filter, timetables, mode=mode, lesson_times=lesson_times)
    etag = '"' + hashlib.sha256(body).hexdigest() + '"'
    headers["ETag"] = etag
    headers["Cache-Control"] = "private, max-age=0, must-revalidate"
    headers["Content-Type"] = "text/calendar; charset=utf-8"
    headers["Content-Disposition"] = 'inline; filename="opencigan.ics"'
    validators = (request_headers or {}).get("If-None-Match", "").strip()
    if validators == "*" or etag in (tag.strip().removeprefix("W/") for tag in validators.split(",")):
        return 304, headers, b""
    headers["Content-Length"] = str(len(body))
    return 200, headers, body
