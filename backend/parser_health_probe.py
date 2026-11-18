"""One-shot parser checks; timetable requests are explicitly opt-in."""

import argparse
import re
from datetime import datetime, timedelta, timezone

from backend.timetable import fetch_timetable, search_schools


def check_parser():
    """Check that one live school search returns valid normalized school records."""
    schools = search_schools("대전")
    if not isinstance(schools, list) or not schools:
        raise RuntimeError("School search returned no valid results")
    for school in schools:
        if (not isinstance(school, dict)
                or not isinstance(school.get("id"), str)
                or not re.fullmatch(r"[0-9]+:[^:]{1,50}", school["id"])
                or not isinstance(school.get("name"), str) or not school["name"]
                or not isinstance(school.get("region"), str)):
            raise RuntimeError("School search response shape changed")
    return len(schools)


def check_timetable_parser(school_id):
    today = datetime.now(timezone(timedelta(hours=9))).date()
    week = (today - timedelta(days=today.weekday())).isoformat()
    timetable = fetch_timetable(school_id, week)
    if (not isinstance(timetable, dict) or timetable.get("schoolId") != school_id
            or timetable.get("weekStart") != week or not isinstance(timetable.get("records"), list)):
        raise RuntimeError("Timetable response shape changed")
    return len(timetable["records"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Check one upstream parser without retries.")
    parser.add_argument("--timetable", metavar="SCHOOL_ID", help="manually check one school's current-week timetable instead of school search")
    args = parser.parse_args()
    if args.timetable is not None:
        count = check_timetable_parser(args.timetable)
        if not count:
            print("Timetable parser check inconclusive: no lessons returned; verify school schedule and upstream.")
            raise SystemExit(2)
        print(f"Timetable parser check passed: {count} normalized lessons; one timetable fetch.")
    else:
        count = check_parser()
        print(f"Parser health passed: {count} schools matched; one school search, no timetable fetch.")
