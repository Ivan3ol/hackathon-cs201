# Події Києва

Збираємо події Києва 

## Concert.ua data

`ConcertuaScraper` follows the shared `BaseScraper` interface, like
`KarabasScraper`. Configure category and city IDs, pagination, language,
sorting, and extra query parameters in the constructor. Repeated IDs can be
lists. Unspecified values retain the endpoint defaults (city `1`, Ukrainian,
limit `24`, offset `0`, popularity sorting).

```python
from scrapers.concertua import ConcertuaScraper

scraper = ConcertuaScraper(category_id=[2, 4], city_id=1, limit=10, offset=0)
events = scraper.scrape()  # list of Event objects
for event in events:
    print(event.to_dict())
```

To get the complete API response as unformatted JSON data instead, use
`fetch_items()` (or its alias `fetch()`):

```python
raw_response = scraper.fetch_items()
```

The raw CLI remains available as `python -m scrapers.concertua --limit 10`.
`services.concertua_pipeline.fetch_events` is also available as a convenience
wrapper. The conversion uses the first
venue and category title, turns relative links into Concert.ua URLs, and treats
timezone-less API start times as Europe/Kyiv local time. Missing or malformed
required event data raises `EventDataError` rather than silently dropping an
event.

```python
from services.concertua_pipeline import fetch_events

events = fetch_events(category_id=2, city_id=1, limit=10, offset=0)
for event in events:
    print(event.to_dict())  # all Event fields; start is an ISO 8601 string
```

Each `Event` also exposes its fields as properties (`event.url`, `event.source`,
`event.category`, `event.price_min`, `event.price_max`, `event.description`,
and `event.image_url`), and its representation shows all fields. The listing
provides category, URL, source, image, and sometimes a minimum price; the full
description and other missing fields may be obtained from the matching event
page's structured data. Listing values take precedence. Prices are integer UAH;
an unspecified price or maximum price stays `None`, and a zero page price is
only used when the listing explicitly marks the event as free.

By default, `scrape()` makes an additional page request for each event with
missing optional fields. This can be slower for large results. Pass
`enrich_details=False` to the constructor to use only the listing response; `items_to_events`
also converts listing data without additional requests. If a detail page cannot
be fetched or contains no matching structured event, a `RuntimeWarning` is
issued and the listing data is retained. The API or event page may genuinely
omit optional data, which remains `None`.

Run the unit tests with the configured project interpreter:

```bash
python -m unittest discover -v
```