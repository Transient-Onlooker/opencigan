import re


def search_timetable_schools(query, cache, query_param, search_schools):
    name = query_param(query, "q", 50)

    def fetch():
        try:
            return {"schools": search_schools(name), "stale": False}
        except ValueError as exc:
            raise RuntimeError("school search failed") from exc

    return cache.get(("school_search", name), fetch)


def get_timetable(query, cache, query_param, validate_week, filters, cached_timetable):
    school = query_param(query, "school", 100)
    if not re.fullmatch(r"[0-9]+:[^:]{1,50}", school):
        raise ValueError("학교 식별자가 올바르지 않습니다")
    week = query_param(query, "week", 10)
    validate_week(week)
    grade_filter, class_filter, teacher_filter = filters(query)
    timetable, cache_status = cached_timetable(school, week, cache)
    result = {**timetable, "cacheStatus": cache_status}
    if grade_filter is not None or class_filter is not None or teacher_filter is not None:
        result["records"] = [
            record for record in timetable["records"]
            if (grade_filter is None or int(record["grade"]) == grade_filter)
            and (class_filter is None or int(record["class"]) == class_filter)
            and (teacher_filter is None or teacher_filter in (record.get("teacher") or "").casefold())
        ]
    return result
