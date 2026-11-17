import os
import re
from datetime import date


def search_meal_schools(query, cache, query_param, client):
    name = query_param(query, "q", 50)
    if not os.environ.get("NEIS_API_KEY", "").strip():
        raise RuntimeError("NEIS API key is not configured")

    def fetch_schools():
        try:
            schools = client.from_environment().search_schools(name)
        except ValueError as exc:
            raise RuntimeError("NEIS school search failed") from exc
        return {
            "schools": [
                {"id": f"{school.office_code}:{school.school_code}", "name": school.name,
                 "region": school.kind, "address": school.address}
                for school in schools
            ],
            "stale": False,
        }

    return cache.get(("neis_school_search", name), fetch_schools)


def get_meals(query, cache, query_param, client, school_type):
    school_id = query_param(query, "school", 20)
    if not re.fullmatch(r"[A-Z]\d{2}:\d{7}", school_id):
        raise ValueError("급식 학교 식별자가 올바르지 않습니다")
    start = date.fromisoformat(query_param(query, "from", 10))
    end = date.fromisoformat(query_param(query, "to", 10))
    if end < start or (end - start).days > 6:
        raise ValueError("급식은 최대 7일 동안 조회할 수 있습니다")
    office, code = school_id.split(":")
    school = school_type(office, code, "")
    if not os.environ.get("NEIS_API_KEY", "").strip():
        raise RuntimeError("NEIS API key is not configured")

    def fetch_meals():
        try:
            meals = client.from_environment().get_meals(school, start, end)
        except ValueError as exc:
            raise RuntimeError("NEIS meal request failed") from exc
        return {
            "meals": [
                {"date": meal.date, "type": meal.meal_type,
                 "dishes": re.split(r"<br\s*/?>", meal.menu, flags=re.I),
                 "calories": meal.calories, "nutrition": meal.nutrition, "origin": meal.origin}
                for meal in meals
            ],
            "stale": False,
        }

    return cache.get(("meals", school_id, start, end), fetch_meals)
