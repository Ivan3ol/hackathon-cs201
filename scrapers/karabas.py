import html
import json
import re
import time
import urllib.request
from datetime import datetime
from typing import Any, Iterator
from zoneinfo import ZoneInfo

from models.event import Event
from models.event_field import EventField as F
from scrapers.base import BaseScraper
from utils.urls import strip_language_prefix

KYIV_TZ = ZoneInfo("Europe/Kyiv")


# Scraper for upcoming events on https://kyiv.karabas.com/
# Uses the site's own catalog API: POST /api/catalog/events (JSON, paginated).
class KarabasScraper(BaseScraper):
    _source = "karabas"

    API_URL = "https://kyiv.karabas.com/api/catalog/events"
    KYIV_CITY_ID = "018e7c1f-0c27-79c2-8e29-1bc5139712e7"
    PER_PAGE = 100
    MAX_PAGES = 200  # safety limit
    DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

    # limit - how many events (cards) to scrape; None = all upcoming events
    def __init__(self, limit: int | None = None, city_id: str = KYIV_CITY_ID,
                 language: str = "uk", timeout: float = 30.0, delay: float = 0.3):
        if limit is not None and limit < 1:
            raise ValueError(f"limit must be >= 1 or None, got {limit!r}")
        self._limit = limit
        self._city_id = city_id
        self._language = language
        self._timeout = timeout
        self._delay = delay

    def scrape(self) -> list[Event]:
        events: list[Event] = []
        for item in self.iter_raw():
            try:
                events.append(self._to_event(item))
            except (KeyError, TypeError, ValueError, AttributeError):
                continue  # skip broken records
            if self._limit is not None and len(events) >= self._limit:
                break
        return events

    # Raw items from the API, without duplicates.
    # One event can have many sessions (same event_id, different event_date),
    # each session is a separate item.
    # Pages are requested lazily, so with a limit only the needed pages are loaded.
    def iter_raw(self) -> Iterator[dict[str, Any]]:
        seen: set[tuple[Any, Any]] = set()

        page = 1
        while page <= self.MAX_PAGES:
            data = self._fetch_page(page)
            for item in data.get("items") or []:
                key = (item.get("event_id"), item.get(F.START.karabas))
                if key in seen:
                    continue
                seen.add(key)
                yield item

            if page >= int(data.get("total_pages") or 0):
                break
            page += 1
            time.sleep(self._delay)

    def _fetch_page(self, page: int) -> dict[str, Any]:
        body = json.dumps({
            "cities": [self._city_id],
            "page": page,
            "per_page": min(self.PER_PAGE, self._limit or self.PER_PAGE),
        }).encode()
        request = urllib.request.Request(self.API_URL, data=body, method="POST", headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Accept-Language": self._language,
            "User-Agent": "Mozilla/5.0 (hackathon-cs201 events scraper)",
        })
        with urllib.request.urlopen(request, timeout=self._timeout) as response:
            return json.load(response)

    def _to_event(self, item: dict[str, Any]) -> Event:
        title = (item.get(F.TITLE.karabas) or "").strip()
        # API returns ".../uk/<slug>/", but on karabas "/uk/..." is 404
        url = strip_language_prefix(item.get(F.URL.karabas) or "")
        if not title or not url:
            raise ValueError("event without title or url")
        venue = item.get(F.VENUE.karabas) or item.get("building_group_name") or ""
        return Event(
            title=title,
            start=datetime.strptime(item[F.START.karabas], self.DATE_FORMAT).replace(tzinfo=KYIV_TZ),
            venue=venue.strip(),
            url=url,
            source=self._source,
            category=self._category(item.get(F.CATEGORY.karabas)),
            price_min=self._price(item.get(F.PRICE_MIN.karabas)),
            price_max=self._price(item.get(F.PRICE_MAX.karabas)),
            description=self._plain_text(item.get(F.DESCRIPTION.karabas)),
            image_url=item.get(F.IMAGE_URL.karabas) or None,
        )

    # "Виставки | Дітям" -> "Виставки, Дітям"
    @staticmethod
    def _category(value: str | None) -> str | None:
        if not value:
            return None
        return ", ".join(part.strip() for part in value.split("|") if part.strip())

    @staticmethod
    def _price(value: Any) -> int | None:
        if value is None or value == "":
            return None
        return int(float(value))

    # HTML description -> plain text
    @staticmethod
    def _plain_text(value: str | None) -> str | None:
        if not value:
            return None
        text = re.sub(r"<br\s*/?>|</p>", "\n", value)
        text = html.unescape(re.sub(r"<[^>]+>", "", text))
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n\s*\n+", "\n\n", text).strip()
        return text or None
