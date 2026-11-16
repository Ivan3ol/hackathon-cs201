import json
from datetime import date, datetime
from typing import Any

from models.event import Event
from models.event_field import EventField


# Common JSON representation of an event, the same for every scraper
def event_to_dict(event: Event) -> dict[str, Any]:
    return {field.key: _plain(getattr(event, field.key)) for field in EventField}


# Any result -> JSON string: list[Event], dict / list from services, etc.
def to_json(data: Any) -> str:
    return json.dumps(_plain(data), ensure_ascii=False, indent=2)


# Saves what a scraper / service returned: save_json(KarabasScraper().scrape(), "events.json")
def save_json(data: Any, path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(to_json(data))


# kept for compatibility
def events_to_json(events: list[Event]) -> str:
    return to_json(events)


def _plain(value: Any) -> Any:
    if isinstance(value, Event):
        return event_to_dict(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()  # e.g. 2026-12-23T18:00:00+02:00
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    return value
