import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "clients" / "python"))
from opensigan import OpensiganClient, OpensiganError


def main():
    client = OpensiganClient(
        base_url=os.environ.get("OPENCIGAN_API_BASE_URL", "http://127.0.0.1:8000"),
        timeout=10,
    )
    query = sys.argv[1] if len(sys.argv) > 1 else "봄빛"
    today = datetime.now(timezone(timedelta(hours=9))).date()
    monday = (today - timedelta(days=today.weekday())).isoformat()

    print("Process:", client.get_status())
    schools = client.search_schools(query)["schools"]
    print("Comcigan schools:", schools)
    if schools:
        school = schools[0]["id"]
        print("Timetable:", client.get_timetable(school, monday, grade=1, classroom=1))
        print("Calendar URL:", client.get_timetable_ics_url(school, 1, 1, weeks=2, mode="periods"))
        print("Timed Calendar URL:", client.get_timetable_ics_url(
            school, 1, 1, weeks=2, mode="timed", times="1:0900-0950,2:1000-1050",
        ))
        try:
            print("History first page:", client.get_timetable_history(school, monday))
        except OpensiganError as error:
            if error.code != "history_disabled":
                raise
            print("History is disabled on this server.")

    schools = client.search_neis_schools(query)["schools"]
    print("NEIS schools (confirm the match before using the ID):", schools)
    if schools:
        print("Meals for first NEIS result:", client.get_meals(schools[0]["id"], today.isoformat(), today.isoformat()))


if __name__ == "__main__":
    try:
        main()
    except OpensiganError as error:
        print("API request failed:", error.status, error.code,
              {"is_timeout": error.is_timeout, "is_network_error": error.is_network_error})
        sys.exit(1)
