"""Select lessons for an opt-in morning reminder without fetching or sending."""

from datetime import date, datetime, timedelta, timezone
import re

from backend.webhook_store import quiet_until, validate_filters


KST = timezone(timedelta(hours=9))


def scheduled_time(day, clock, quiet_hours=None):
    """Return the KST scheduled instant, deferred through quiet hours if needed."""
    if type(day) is not date or not isinstance(clock, str) or not re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", clock):
        raise ValueError("invalid schedule time")
    if quiet_hours is not None:
        validate_filters({"quietHours": quiet_hours})
    scheduled = datetime.combine(day, datetime.strptime(clock, "%H:%M").time(), KST)
    deferred = quiet_until(scheduled.timestamp(), quiet_hours)
    return datetime.fromtimestamp(deferred, KST) if deferred is not None else scheduled


def scheduled_event_id(subscription_id, mode, day):
    """Keep one stable event identity per subscription, mode and KST day."""
    if (not isinstance(subscription_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{24}", subscription_id)
            or mode not in ("daily_summary", "subject_prep") or type(day) is not date):
        raise ValueError("invalid scheduled event identity")
    return f"scheduled_{mode}_{subscription_id}_{day:%Y%m%d}"


def preparation_periods(response, school, grade, classroom, subject, now, max_age, filters=None):
    """Return today's matching periods, or None when the source is not usable."""
    if not isinstance(response, dict) or response.get("schoolId") != school or response.get("stale") is not False:
        return None
    if not isinstance(now, datetime) or now.tzinfo is None or not isinstance(max_age, timedelta) or max_age <= timedelta(0):
        raise ValueError("an aware clock and positive freshness limit are required")
    if type(grade) is not int or type(classroom) is not int or not isinstance(subject, str) or not subject.strip():
        raise ValueError("invalid lesson selection")
    filters = validate_filters(filters or {})
    try:
        fetched = datetime.fromisoformat(response["fetchedAt"].replace("Z", "+00:00"))
        if fetched.tzinfo is None:
            return None
        age = now.astimezone(timezone.utc) - fetched.astimezone(timezone.utc)
        today = now.astimezone(KST).date()
        monday = today - timedelta(days=today.weekday())
        if age < timedelta(0) or age > max_age or response.get("weekStart") != monday.isoformat():
            return None
        records = response["records"]
        if not isinstance(records, list) or not records:
            return None
        periods = set()
        for lesson in records:
            if not isinstance(lesson, dict):
                return None
            lesson_grade, lesson_class = lesson.get("grade"), lesson.get("class")
            period, lesson_date, lesson_subject = lesson.get("period"), lesson.get("date"), lesson.get("subject")
            if (type(lesson_grade) is not int or isinstance(lesson_class, bool)
                    or not isinstance(lesson_class, (int, str)) or not str(lesson_class).isdigit()
                    or type(period) is not int or not 1 <= period <= 20
                    or not isinstance(lesson_date, str) or not isinstance(lesson_subject, str)):
                return None
            parsed_date = date.fromisoformat(lesson_date)
            if parsed_date.isoformat() != lesson_date or parsed_date < monday or parsed_date > monday + timedelta(days=6):
                return None
            if (lesson_grade == grade and int(lesson_class) == classroom and lesson_date == today.isoformat()
                    and lesson_subject.strip() == subject.strip()
                    and (filters.get("weekday") is None or filters["weekday"] == today.isoweekday())
                    and (filters.get("period") is None or filters["period"] == period)
                    and (not filters.get("subject") or filters["subject"] in lesson_subject)
                    and (not filters.get("teacher") or filters["teacher"] in (lesson.get("teacher") or ""))):
                periods.add(period)
        return sorted(periods)
    except (KeyError, TypeError, ValueError, OverflowError):
        return None
