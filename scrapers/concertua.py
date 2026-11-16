import html
import json
import re
import time
import urllib.parse
import urllib.request
from collections.abc import Iterator
from datetime import datetime
from typing import Any

from config import KYIV_TZ
from models.event import Event
from models.event_field import EventField as F
from scrapers.base import BaseScraper


# TODO add proper support for groups
# Scraper for upcoming events on https://concert.ua, uses the site's catalog API: GET /api/v3/items (JSON, paginated by offset)
class ConcertuaScraper(BaseScraper):
    _source = "concert_ua"

    BASE_URL = "https://concert.ua"
    API_URL = "https://concert.ua/api/v3/items"
    KYIV_CITY_ID = 1
    PER_PAGE = 100
    MAX_PAGES = 50  # safety limit
    DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
    _BLOCK_TAGS = re.compile(r"<br\s*/?>|</(p|li|div|h\d)>", re.IGNORECASE)
    _JSON_LD = re.compile(
        r"<script[^>]*application/ld\+json[^>]*>(.*?)</script>", re.IGNORECASE | re.DOTALL
    )

    # limit - how many API items (different events) to scrape, none = all upcoming events
    # a group counts as one item with all its shows
    # expand_groups - load group pages to split groups into shows (one request per group)
    def __init__(
        self,
        limit: int | None = None,
        city_id: int = KYIV_CITY_ID,
        language: str = "uk",
        timeout: float = 30.0,
        delay: float = 1.0,
        expand_groups: bool = True,
    ):
        if limit is not None and limit < 1:
            raise ValueError(f"limit must be >= 1 or None, got {limit!r}")
        self._limit = limit
        self._city_id = city_id
        self._language = language
        self._timeout = timeout
        self._delay = delay
        self._expand_groups = expand_groups

    def scrape(self) -> list[Event]:
        events: list[Event] = []
        seen: set[tuple[str, datetime]] = set()
        items_done = 0
        for item in self.iter_raw():
            try:
                item_events = self._to_events(item)
            except (KeyError, TypeError, ValueError, AttributeError):
                continue  # skip broken records
            for event in item_events:
                # a show can come both inside a group and as a separate item
                if (event.url, event.start) in seen:
                    continue
                seen.add((event.url, event.start))
                events.append(event)
            items_done += 1
            if self._limit is not None and items_done >= self._limit:
                break
        return events

    # Raw items from the API
    def iter_raw(self) -> Iterator[dict[str, Any]]:
        per_page = min(self.PER_PAGE, self._limit or self.PER_PAGE)
        for page in range(self.MAX_PAGES):
            items = self._fetch_page(page * per_page, per_page).get("items") or []
            yield from items
            if len(items) < per_page:
                break
            time.sleep(self._delay)

    def _fetch_page(self, offset: int, limit: int) -> dict[str, Any]:
        query = urllib.parse.urlencode(
            {
                "citiesIds[]": self._city_id,
                "language": self._language,
                "limit": limit,
                "offset": offset,
                "sortType": "sort_by_date",
            }
        )
        return json.loads(self._get(f"{self.API_URL}?{query}", "application/json"))

    def _get(self, url: str, accept: str) -> str:
        request = urllib.request.Request(
            url,
            headers={
                "Accept": accept,
                "Accept-Language": self._language,
                "User-Agent": "Mozilla/5.0 (hackathon-cs201 events scraper)",
            },
        )
        with urllib.request.urlopen(request, timeout=self._timeout) as response:
            return response.read().decode("utf-8")

    def _to_events(self, item: dict[str, Any]) -> list[Event]:
        is_group = item.get("entityType") == "Group"
        has_one_show = (item.get("eventCount") or 1) == 1 and item.get(F.START.concert_ua)
        if not is_group or has_one_show or not self._expand_groups:
            return [self._from_item(item)]
        try:
            return self._from_group_page(item)
        except (OSError, ValueError):
            return [self._from_item(item)]  # page unavailable: keep the first show only

    # One show straight from the API item
    def _from_item(self, item: dict[str, Any]) -> Event:
        title = (item.get(F.TITLE.concert_ua) or "").strip()
        link = item.get(F.URL.concert_ua) or ""
        start = item.get(F.START.concert_ua)
        if not title or not link or not start:
            raise ValueError("event without title, url or start")
        uah = item.get("currency", "UAH") == "UAH"
        return Event(
            title=title,
            start=datetime.strptime(start, self.DATE_FORMAT).replace(tzinfo=KYIV_TZ),
            venue=self._first(item.get(F.VENUE.concert_ua)),
            url=urllib.parse.urljoin(self.BASE_URL, link),
            source=self._source,
            category=self._category(item.get(F.CATEGORY.concert_ua)),
            price_min=self._price(item.get(F.PRICE_MIN.concert_ua)) if uah else None,
            image_url=item.get(F.IMAGE_URL.concert_ua) or None,
        )

    # All shows of a group from the JSON-LD on its page
    def _from_group_page(self, item: dict[str, Any]) -> list[Event]:
        time.sleep(self._delay)
        page = self._get(urllib.parse.urljoin(self.BASE_URL, item[F.URL.concert_ua]), "text/html")
        events = []
        for node in self._json_ld_events(page):
            try:
                events.append(self._from_json_ld(item, node))
            except (KeyError, TypeError, ValueError, AttributeError):
                continue
        if not events:
            raise ValueError("no shows found on the group page")
        return events

    def _from_json_ld(self, item: dict[str, Any], node: dict[str, Any]) -> Event:
        title = (item.get(F.TITLE.concert_ua) or "").strip()
        if not title:
            raise ValueError("event without title")
        location = node.get("location")
        venue = location.get("name") if isinstance(location, dict) else None
        price_min, price_max = self._offer_prices(node.get("offers"))
        return Event(
            title=title,
            start=datetime.fromisoformat(node["startDate"]).astimezone(KYIV_TZ),
            venue=(venue or self._first(item.get(F.VENUE.concert_ua))).strip(),
            url=node.get("url") or urllib.parse.urljoin(self.BASE_URL, item[F.URL.concert_ua]),
            source=self._source,
            category=self._category(item.get(F.CATEGORY.concert_ua)),
            price_min=price_min,
            price_max=price_max,
            description=self._plain_text(node.get("description")),
            image_url=item.get(F.IMAGE_URL.concert_ua) or None,
        )

    # schema.org Event objects from <script type="application/ld+json"> blocks
    @classmethod
    def _json_ld_events(cls, page: str) -> list[dict[str, Any]]:
        found = []
        for block in cls._JSON_LD.findall(page):
            try:
                data = json.loads(block)
            except json.JSONDecodeError:
                continue
            for node in data if isinstance(data, list) else [data]:
                types = node.get("@type") if isinstance(node, dict) else None
                types = types if isinstance(types, list) else [types]
                if any(isinstance(t, str) and t.endswith("Event") for t in types):
                    found.append(node)
        return found

    # (min, max) price in UAH from schema.org offers, max is None if equal to min
    @classmethod
    def _offer_prices(cls, offers: Any) -> tuple[int | None, int | None]:
        offers = offers if isinstance(offers, list) else [offers]
        lows, highs = [], []
        for offer in offers:
            if not isinstance(offer, dict) or offer.get("priceCurrency", "UAH") != "UAH":
                continue
            low = cls._price(offer.get("lowPrice", offer.get("price")))
            high = cls._price(offer.get("highPrice"))
            if low is not None:
                lows.append(low)
            if high is not None:
                highs.append(high)
        price_min = min(lows) if lows else None
        price_max = max(highs) if highs else None
        return price_min, price_max if price_max != price_min else None

    @staticmethod
    def _category(values: list[str] | None) -> str | None:
        parts = [v.strip() for v in values or [] if v and v.strip()]
        return ", ".join(parts) or None

    # first non-empty title from an API list, e.g. venuesTitles
    @staticmethod
    def _first(values: list[str] | None) -> str:
        return next((v.strip() for v in values or [] if v and v.strip()), "")

    @staticmethod
    def _price(value: Any) -> int | None:
        if value is None or value == "":
            return None
        return int(float(value))

    # HTML description to plain text
    @classmethod
    def _plain_text(cls, value: str | None) -> str | None:
        if not value:
            return None
        text = cls._BLOCK_TAGS.sub("\n", value)
        text = html.unescape(re.sub(r"<[^>]+>", "", text))
        text = re.sub(r"[ \t\xa0]+", " ", text)
        text = "\n".join(line.strip() for line in text.split("\n"))
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        return text or None
