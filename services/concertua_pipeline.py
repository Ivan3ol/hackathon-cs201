"""Convert raw Concert.ua API data into the shared event model."""

import json
import warnings
from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from models.event import Event
from scrapers.concertua import DEFAULT_TIMEOUT, ConcertuaScraper


CONCERTUA_URL = "https://concert.ua/"
CONCERTUA_SOURCE = "Concert.ua"
KYIV_TIMEZONE = ZoneInfo("Europe/Kyiv")


class EventDataError(ValueError):
    """Raised when a raw API item cannot be represented as an Event."""


def _required_text(item, field, item_index):
    value = item.get(field)
    if not isinstance(value, str) or not value.strip():
        raise EventDataError(
            f"item {item_index} has no valid required field {field!r}"
        )
    return value.strip()


def _first_title(item, field):
    values = item.get(field)
    if not isinstance(values, list):
        return None
    return next(
        (value.strip() for value in values if isinstance(value, str) and value.strip()),
        None,
    )


def _optional_text(item, field, item_index):
    value = item.get(field)
    if value is None:
        return None
    if not isinstance(value, str):
        raise EventDataError(f"item {item_index} has invalid optional field {field!r}")
    return value or None


def _event_start(value, item_index):
    if not isinstance(value, str):
        raise EventDataError(f"item {item_index} has no valid required field 'dateStart'")
    try:
        start = datetime.fromisoformat(value)
    except ValueError as error:
        raise EventDataError(
            f"item {item_index} has invalid start datetime {value!r}"
        ) from error
    if start.tzinfo is None:
        return start.replace(tzinfo=KYIV_TIMEZONE)
    return start.astimezone(KYIV_TIMEZONE)


def _optional_price(item, field, item_index):
    value = item.get(field)
    if value is None:
        return None
    if type(value) is not int:
        raise EventDataError(f"item {item_index} has invalid optional field {field!r}")
    return value


def _optional_image(item, item_index):
    value = item.get("posterUrl")
    if value is None:
        return None
    if not isinstance(value, str):
        raise EventDataError(f"item {item_index} has invalid optional field 'posterUrl'")
    return urljoin(CONCERTUA_URL, value) if value else None


class _JsonLdParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.scripts = []
        self._parts = None

    def handle_starttag(self, tag, attrs):
        script_type = (dict(attrs).get("type") or "").lower().split(";")[0].strip()
        if tag.lower() == "script" and script_type == "application/ld+json":
            self._parts = []

    def handle_data(self, data):
        if self._parts is not None:
            self._parts.append(data)

    def handle_endtag(self, tag):
        if tag.lower() == "script" and self._parts is not None:
            self.scripts.append("".join(self._parts))
            self._parts = None


def _json_ld_nodes(value):
    if isinstance(value, list):
        for item in value:
            yield from _json_ld_nodes(item)
    elif isinstance(value, dict):
        yield value
        yield from _json_ld_nodes(value.get("@graph"))


def _same_event_url(candidate, event_url):
    if not isinstance(candidate, str):
        return False
    candidate_parts = urlsplit(urljoin(event_url, candidate))
    event_parts = urlsplit(event_url)
    return (
        candidate_parts.scheme in ("http", "https")
        and candidate_parts.hostname == event_parts.hostname
        and candidate_parts.port == event_parts.port
        and candidate_parts.path.rstrip("/") == event_parts.path.rstrip("/")
    )


def _fetch_event_details(event_url, timeout):
    parts = urlsplit(event_url)
    if (
        parts.scheme != "https"
        or parts.hostname != "concert.ua"
        or parts.port not in (None, 443)
    ):
        raise ValueError("event detail URL must be on https://concert.ua")
    request = Request(
        event_url, headers={"Accept": "text/html", "User-Agent": "Mozilla/5.0"}
    )
    with urlopen(request, timeout=timeout) as response:
        html = response.read().decode("utf-8")
    parser = _JsonLdParser()
    parser.feed(html)
    for script in parser.scripts:
        try:
            data = json.loads(script)
        except json.JSONDecodeError:
            continue
        for node in _json_ld_nodes(data):
            types = node.get("@type")
            if isinstance(types, str):
                types = [types]
            if not isinstance(types, list):
                continue
            if any(
                isinstance(kind, str) and kind.rsplit("/", 1)[-1].endswith("Event")
                for kind in types
            ):
                if _same_event_url(node.get("url"), event_url):
                    return node
    raise ValueError("no matching event JSON-LD found")


def _detail_price(value, *, allow_zero: bool):
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return None
    try:
        price = Decimal(str(value))
    except InvalidOperation:
        return None
    if not price.is_finite() or price != price.to_integral_value() or price < 0:
        return None
    if price.is_zero() and not allow_zero:
        return None
    return int(price)


def _merge_event_details(item, details):
    enriched = dict(item)
    description = details.get("description")
    if (
        not enriched.get("description")
        and isinstance(description, str)
        and description.strip()
    ):
        enriched["description"] = description.strip()

    image = details.get("image")
    if isinstance(image, list):
        image = next(
            (value for value in image if isinstance(value, str) and value.strip()),
            None,
        )
    if not enriched.get("posterUrl") and isinstance(image, str) and image.strip():
        enriched["posterUrl"] = urljoin(CONCERTUA_URL, image.strip())

    if not _first_title(enriched, "categoriesTitles"):
        category = details.get("genre")
        if isinstance(category, str):
            category = [category]
        if isinstance(category, list):
            enriched["categoriesTitles"] = category

    offers = details.get("offers")
    if isinstance(offers, Mapping):
        offers = [offers]
    if not isinstance(offers, list):
        return enriched
    minimums, maximums = [], []
    for offer in offers:
        if not isinstance(offer, Mapping) or offer.get("priceCurrency", "UAH") != "UAH":
            continue
        if str(offer.get("availability", "")).rstrip("/").endswith("SoldOut"):
            continue
        allow_zero = item.get("isFreeEntrance") is True
        minimum = _detail_price(
            offer.get("lowPrice", offer.get("price")), allow_zero=allow_zero
        )
        maximum = _detail_price(offer.get("highPrice"), allow_zero=allow_zero)
        if minimum is not None:
            minimums.append(minimum)
        if maximum is not None:
            maximums.append(maximum)
    if enriched.get("priceMin") is None and minimums:
        enriched["priceMin"] = min(minimums)
    if enriched.get("priceMax") is None and maximums:
        enriched["priceMax"] = max(maximums)
    return enriched


def item_to_event(item, item_index=0):
    """Map one raw API item to an Event, rejecting missing required data."""
    if not isinstance(item, Mapping):
        raise EventDataError(f"item {item_index} is not a JSON object")

    title = _required_text(item, "title", item_index)
    venue = _first_title(item, "venuesTitles")
    if venue is None:
        raise EventDataError(f"item {item_index} has no valid required field 'venuesTitles'")
    event_url = urljoin(CONCERTUA_URL, _required_text(item, "link", item_index))
    category = _first_title(item, "categoriesTitles")

    return Event(
        title=title,
        start=_event_start(item.get("dateStart"), item_index),
        venue=venue,
        url=event_url,
        source=CONCERTUA_SOURCE,
        category=category,
        price_min=_optional_price(item, "priceMin", item_index),
        price_max=_optional_price(item, "priceMax", item_index),
        description=_optional_text(item, "description", item_index),
        image_url=_optional_image(item, item_index),
    )


def items_to_events(response):
    """Convert the response's items array to Event objects."""
    if not isinstance(response, Mapping):
        raise EventDataError("Concert.ua response must be a JSON object")
    items = response.get("items")
    if not isinstance(items, list):
        raise EventDataError("Concert.ua response has no valid 'items' array")
    return [item_to_event(item, index) for index, item in enumerate(items)]


def fetch_events(
    category_id=None,
    city_id=None,
    limit=None,
    offset=None,
    *,
    language=None,
    sort_type=None,
    timeout=DEFAULT_TIMEOUT,
    params=None,
    enrich_details=True,
):
    """Fetch raw API data and return its items formatted as Event objects."""
    return ConcertuaScraper(
        timeout=timeout,
        category_id=category_id,
        city_id=city_id,
        language=language,
        limit=limit,
        offset=offset,
        sort_type=sort_type,
        params=params,
        enrich_details=enrich_details,
    ).scrape()


def response_to_events(response, *, timeout=DEFAULT_TIMEOUT, enrich_details=True):
    """Convert a raw response and optionally enrich missing event details."""
    events = items_to_events(response)
    if not enrich_details:
        return events
    enriched_events = []
    for index, (item, event) in enumerate(zip(response["items"], events)):
        if all(
            value is not None for value in (
                event.category, event.price_min, event.price_max,
                event.description, event.image_url,
            )
        ):
            enriched_events.append(event)
            continue
        try:
            details = _fetch_event_details(event.url, timeout)
            enriched_events.append(item_to_event(_merge_event_details(item, details), index))
        except (OSError, ValueError) as error:
            warnings.warn(
                f"Could not enrich event {event.url}: {error}",
                RuntimeWarning,
                stacklevel=2,
            )
            enriched_events.append(event)
    return enriched_events


if __name__ == "__main__":
    print(json.dumps(
        [event.to_dict() for event in fetch_events(
            limit=1, offset=10, sort_type="sort_by_popularity"
        )],
        ensure_ascii=False,
        indent=2,
    ))