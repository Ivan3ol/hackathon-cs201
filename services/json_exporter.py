import json
from datetime import datetime
from typing import Any

from models.event import Event
from models.event_field import EventField


# Common JSON representation of an event, the same for every scraper
def event_to_dict(event: Event) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for field in EventField:
        value = getattr(event, field.key)
        if isinstance(value, datetime):
            value = value.isoformat()  # e.g. 2026-12-23T18:00:00+02:00
        result[field.key] = value
    return result


def events_to_json(events: list[Event]) -> str:
    return json.dumps([event_to_dict(e) for e in events], ensure_ascii=False, indent=2)


def save_json(events: list[Event], path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(events_to_json(events))
