"""Explicitly enabled scheduler; it queues notifications but never sends them."""

import json
import logging
import os
import signal
import sqlite3
import threading
from contextlib import closing
from datetime import date, datetime, time, timedelta, timezone

from backend.cache import Cache
from backend.scheduled_lessons import KST, preparation_periods, scheduled_time
from backend.scheduled_store import ScheduledStore
from backend.webhook_store import validate_filters
from backend.webhook_templates import render_template

logger = logging.getLogger("opensigan.scheduler")


def _lesson(value):
    if value is None:
        return "없음"
    if not isinstance(value, dict) or not all(isinstance(value.get(key), str) for key in ("subject", "teacher")):
        raise ValueError("invalid history lesson")
    return " · ".join(part for part in (value["subject"], value["teacher"]) if part) or "정보 없음"


def _history_summary(store, schedule, day, deadline, filters):
    start = datetime.combine(day, time.min, KST).astimezone(timezone.utc)
    end = min(start + timedelta(days=1), deadline.astimezone(timezone.utc))
    lines, count = [], 0
    with closing(store._connect()) as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='changes'").fetchone():
            return None
        rows = db.execute("""SELECT date, period, type, before_json, after_json FROM changes
                             WHERE school=? AND grade=? AND class_number=? AND observed_at>=? AND observed_at<?
                             ORDER BY observed_at, id""",
                          (schedule["school"], schedule["grade"], schedule["classroom"], start.isoformat(), end.isoformat()))
        for row in rows:
            lesson_day = date.fromisoformat(row["date"])
            before = json.loads(row["before_json"]) if row["before_json"] is not None else None
            after = json.loads(row["after_json"]) if row["after_json"] is not None else None
            old, new = _lesson(before), _lesson(after)
            if any(filters.get(key) is not None and filters[key] != value for key, value in
                   (("period", row["period"]), ("type", row["type"]), ("weekday", lesson_day.isoweekday()))):
                continue
            if any(filters.get(key) and not any(filters[key] in (value or {}).get(key, "") for value in (before, after))
                   for key in ("subject", "teacher")):
                continue
            count += 1
            line = f"{row['date'][5:]} {row['period']}교시 {old} → {new}"
            if len(lines) < 20 and sum(len(item) + 1 for item in lines) + len(line) <= 1000:
                lines.append(line)
        if count == 0:
            return None
    if count > len(lines):
        lines.append(f"외 {count - len(lines)}건")
    return lines


def run_once(store, cache, fetch_timetable, now, *, enabled=False):
    """Process due schedules using injected data access; default is inert."""
    if not enabled:
        return 0
    if not isinstance(now, datetime) or now.tzinfo is None:
        raise ValueError("an aware clock is required")
    local = now.astimezone(KST)
    store.prune_occurrences(local.date())
    queued = 0
    for schedule in store.active_schedules():
        try:
            filters = validate_filters(json.loads(schedule["filters_json"]))
            for day in (local.date() - timedelta(days=1), local.date()):
                due = scheduled_time(day, schedule["time_kst"], filters.get("quietHours"))
                if due.date() != local.date() or due > local or store.already_handled(schedule["subscription_id"], schedule["mode"], day.isoformat()):
                    continue
                if schedule["mode"] == "subject_prep":
                    if day != local.date():
                        store.mark_noop(schedule["subscription_id"], schedule["revision"], day.isoformat(), expected_filters=schedule["filters_json"])
                        continue
                    week = (day - timedelta(days=day.weekday())).isoformat()
                    key = ("timetable", schedule["school"], week)
                    response = cache.get(key, lambda: fetch_timetable(schedule["school"], week))
                    periods = preparation_periods(response, schedule["school"], schedule["grade"], schedule["classroom"],
                                                  schedule["subject"], now, timedelta(minutes=30), filters)
                    if periods is None:
                        continue
                    lines = [f"{schedule['subject']} · {', '.join(str(period) + '교시' for period in periods)}"] if periods else []
                else:
                    lines = _history_summary(store, schedule, day, due, filters)
                    if lines is None:
                        continue
                if not lines:
                    store.mark_noop(schedule["subscription_id"], schedule["revision"], day.isoformat(), expected_filters=schedule["filters_json"])
                    continue
                values = {"school": schedule["school"].split(":", 1)[-1], "grade": schedule["grade"],
                          "classroom": schedule["classroom"], "date": day.isoformat(), "after": "\n".join(lines)}
                payload = render_template(schedule["provider"], "{school} {grade}학년 {classroom}반 · {date}\n{after}", values)
                body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
                if store.enqueue_due(schedule["subscription_id"], schedule["revision"], day.isoformat(), body, due.timestamp(), expected_filters=schedule["filters_json"]):
                    queued += 1
        except (ValueError, TypeError, KeyError, OSError, RuntimeError, sqlite3.Error):
            logger.warning("scheduled notification skipped due to unavailable or invalid data")
    return queued


def main():
    path = os.environ.get("OPENCIGAN_HISTORY_DB", "").strip()
    if (os.environ.get("OPENCIGAN_WEBHOOKS_ENABLED") != "1" or os.environ.get("OPENCIGAN_SCHEDULER_ENABLED") != "1"
            or not path or not os.path.isfile(path)):
        raise SystemExit("Scheduler requires explicitly enabled features and an existing history database")
    from backend.timetable import fetch_timetable
    stop = threading.Event()
    for name in ("SIGINT", "SIGTERM"):
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), lambda *_: stop.set())
    store, cache = ScheduledStore(path), Cache()
    while not stop.is_set():
        try:
            run_once(store, cache, fetch_timetable, datetime.now(timezone.utc), enabled=True)
        except (OSError, sqlite3.Error):
            logger.warning("scheduled worker storage unavailable")
        stop.wait(30)


if __name__ == "__main__":
    main()
