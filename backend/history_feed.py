"""RSS rendering for observed timetable changes."""

import hashlib
import html
import re
from datetime import datetime
from email.utils import format_datetime
from xml.etree.ElementTree import Element, SubElement, tostring


def render_history_feed(school, grade, classroom, changes, group="changes"):
    def clean(value):
        return re.sub(r"[^\x09\x0a\x0d\x20-\ud7ff\ue000-\ufffd\U00010000-\U0010ffff]", "", str(value))

    def child(parent, tag, value):
        SubElement(parent, tag).text = clean(value)

    rss = Element("rss", {"version": "2.0"})
    channel = SubElement(rss, "channel")
    child(channel, "title", f"{school.split(':', 1)[-1]} {grade}학년 {classroom}반 시간표 변경")
    child(channel, "link", "https://opencigan.mcv.kr/")
    child(channel, "description", "관측된 시간표 변경입니다. 관측 사이의 변경은 누락될 수 있습니다.")
    school_hash = hashlib.sha256(school.encode("utf-8")).hexdigest()[:16]
    grouped = {}
    for change in changes:
        grouped.setdefault(change["date"] if group == "daily" else str(change["_id"]), []).append(change)
    for changes_in_item in grouped.values():
        change = changes_in_item[0]
        item = SubElement(channel, "item")
        child(item, "title", f"{change['date']} 시간표 변경 {len(changes_in_item)}건" if group == "daily"
              else f"{change['date']} {change['period']}교시 {change['type']}")
        def lesson(value):
            if value is None:
                return "없음"
            return " · ".join(part for part in (value.get("subject"), value.get("teacher")) if part) or "정보 없음"
        lines = [f"{entry['period']}교시 {lesson(entry['before'])} → {lesson(entry['after'])}"
                 if group == "daily" else f"{lesson(entry['before'])} → {lesson(entry['after'])}"
                 for entry in changes_in_item]
        child(item, "description", "<br/>".join(html.escape(line) for line in lines))
        if group == "daily":
            ids = ",".join(str(entry["_id"]) for entry in changes_in_item)
            identifier = f"daily:{change['date']}:{hashlib.sha256(ids.encode()).hexdigest()[:16]}"
        else:
            identifier = str(change["_id"])
        child(item, "guid", f"urn:opencigan:history:{school_hash}:{identifier}")
        item.find("guid").set("isPermaLink", "false")
        child(item, "pubDate", format_datetime(datetime.fromisoformat(change["observedAt"].replace("Z", "+00:00"))))
    return b'<?xml version="1.0" encoding="UTF-8"?>\n' + tostring(rss, encoding="utf-8")
