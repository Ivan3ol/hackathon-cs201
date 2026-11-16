import io
import json
import unittest
from datetime import datetime
from email.message import Message
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlsplit
from zoneinfo import ZoneInfo

from scrapers import concertua as scraper
from scrapers.base import BaseScraper
from services import concertua_pipeline as pipeline


class FetchItemsTests(unittest.TestCase):
    @patch("scrapers.concertua.ConcertuaScraper.fetch_items", return_value={"items": []})
    def test_fetch_accepts_category_city_limit_and_offset(self, fetch_items):
        instance = scraper.ConcertuaScraper(4, 2, 10, 20, params={"isOnline": True})
        result = instance.fetch()

        self.assertIsInstance(instance, BaseScraper)
        self.assertEqual({"items": []}, result)
        fetch_items.assert_called_once_with()

    @patch("scrapers.concertua.urlopen")
    def test_fetch_returns_raw_json_and_builds_configurable_query(self, urlopen):
        payload = {"offset": 4, "itemsCount": 1, "items": [{"title": "Подія"}]}
        urlopen.return_value.__enter__.return_value = io.BytesIO(
            json.dumps(payload, ensure_ascii=False).encode("utf-8")
        )

        result = scraper.ConcertuaScraper(
            category_id=[4, 7], city_id=2, limit=0, offset=4,
            params={"tag[]": ["music", "theatre"]},
        ).fetch_items()

        self.assertEqual(payload, result)
        request = urlopen.call_args.args[0]
        self.assertEqual(
            [
                ("language", "uk"),
                ("sortType", "sort_by_popularity"),
                ("categoriesIds[]", "4"),
                ("categoriesIds[]", "7"),
                ("citiesIds[]", "2"),
                ("limit", "0"),
                ("offset", "4"),
                ("tag[]", "music"),
                ("tag[]", "theatre"),
            ],
            parse_qsl(urlsplit(request.full_url).query),
        )

    @patch(
        "scrapers.concertua.urlopen",
        side_effect=HTTPError("url", 503, "Unavailable", Message(), None),
    )
    def test_http_errors_are_reported(self, _urlopen):
        with self.assertRaisesRegex(scraper.APIError, "HTTP 503"):
            scraper.ConcertuaScraper().fetch_items()

    @patch(
        "scrapers.concertua.urlopen",
        side_effect=URLError("offline"),
    )
    def test_network_errors_are_reported(self, _urlopen):
        with self.assertRaisesRegex(scraper.APIError, "offline"):
            scraper.ConcertuaScraper().fetch_items()

    @patch("scrapers.concertua.urlopen")
    def test_invalid_json_is_reported(self, urlopen):
        urlopen.return_value.__enter__.return_value = io.BytesIO(b"not json")
        with self.assertRaisesRegex(scraper.APIError, "valid UTF-8 JSON"):
            scraper.ConcertuaScraper().fetch_items()

    def test_existing_url_and_extra_overrides_are_preserved(self):
        instance = scraper.ConcertuaScraper(
            city_id=[1, 2], offset=0,
            url="https://concert.ua/api/v3/items?custom=kept&limit=5",
            params={"limit": 0, "tag[]": ["музика & театр", "concert"]},
        )
        self.assertEqual(
            [("custom", "kept"), ("citiesIds[]", "1"), ("citiesIds[]", "2"),
             ("offset", "0"), ("limit", "0"), ("tag[]", "музика & театр"),
             ("tag[]", "concert")],
            parse_qsl(urlsplit(instance.build_items_url()).query),
        )


class EventPipelineTests(unittest.TestCase):
    def setUp(self):
        self.raw_item: dict[str, object] = {
            "title": "Галицька Діва",
            "dateStart": "2026-12-04 19:00:00",
            "venuesTitles": ["Будинок Актора"],
            "link": "/uk/event/halytska-diva",
            "categoriesTitles": ["Театр"],
            "priceMin": 500,
            "posterUrl": "https://storage.concert.ua/poster.png",
        }

    def test_maps_api_item_to_timezone_aware_event(self):
        event = pipeline.item_to_event(self.raw_item)

        self.assertEqual("Галицька Діва", event.title)
        self.assertEqual(datetime(2026, 12, 4, 19, 0, tzinfo=ZoneInfo("Europe/Kyiv")), event.start)
        self.assertEqual("Будинок Актора", event.venue)
        self.assertEqual("https://concert.ua/uk/event/halytska-diva", event.url)
        self.assertEqual("Concert.ua", event.source)
        self.assertEqual("Театр", event.category)
        self.assertEqual(500, event.price_min)
        self.assertIsNone(event.price_max)
        self.assertIsNone(event.description)
        self.assertEqual("https://storage.concert.ua/poster.png", event.image_url)

    @patch("scrapers.concertua.urlopen")
    def test_class_scrape_fetches_and_converts_with_configured_timeout(self, urlopen):
        urlopen.return_value.__enter__.return_value = io.BytesIO(
            json.dumps({"items": [self.raw_item]}).encode("utf-8")
        )
        instance = scraper.ConcertuaScraper(
            category_id=4, city_id=2, limit=1, timeout=7, enrich_details=False,
        )
        events = instance.scrape()
        self.assertEqual("Галицька Діва", events[0].title)
        self.assertEqual(7, urlopen.call_args.kwargs["timeout"])
        self.assertIn(
            ("categoriesIds[]", "4"),
            parse_qsl(urlsplit(urlopen.call_args.args[0].full_url).query),
        )

    def test_maps_optional_values_and_timezone_offsets(self):
        self.raw_item.update(
            dateStart="2026-12-04T17:00:00+00:00",
            venuesTitles=["First venue", "Second venue"],
            categoriesTitles=[],
            priceMin=None,
            priceMax=None,
            description="Details",
            posterUrl=None,
        )

        event = pipeline.item_to_event(self.raw_item)

        self.assertEqual("First venue", event.venue)
        self.assertIsNone(event.category)
        self.assertEqual(19, event.start.hour)
        self.assertEqual("Details", event.description)
        self.assertIsNone(event.image_url)

    def test_event_serialization_and_repr_expose_every_field(self):
        event = pipeline.item_to_event(self.raw_item)

        self.assertEqual(
            {
                "title": "Галицька Діва",
                "start": "2026-12-04T19:00:00+02:00",
                "venue": "Будинок Актора",
                "url": "https://concert.ua/uk/event/halytska-diva",
                "source": "Concert.ua",
                "category": "Театр",
                "price_min": 500,
                "price_max": None,
                "description": None,
                "image_url": "https://storage.concert.ua/poster.png",
            },
            event.to_dict(),
        )
        for value in (event.url, event.source, event.category, event.image_url):
            self.assertIn(value, repr(event))

    @patch("services.concertua_pipeline._fetch_event_details")
    @patch("scrapers.concertua.ConcertuaScraper.fetch_items")
    def test_fetch_events_enriches_from_matching_event_json_ld(
        self, fetch_items, fetch_details
    ):
        self.raw_item.update(priceMin=None, categoriesTitles=["Театр", "Музика"])
        fetch_items.return_value = {"items": [self.raw_item]}
        fetch_details.return_value = {
            "@type": "MusicEvent",
            "url": "https://concert.ua/uk/event/halytska-diva",
            "description": "Full event description",
            "image": ["https://storage.concert.ua/details.png"],
            "offers": {"price": 0, "availability": "https://schema.org/InStock"},
        }

        event = pipeline.fetch_events(limit=1)[0]

        self.assertEqual("Театр", event.category)
        self.assertEqual("https://concert.ua/uk/event/halytska-diva", event.url)
        self.assertEqual("Concert.ua", event.source)
        self.assertEqual("Full event description", event.description)
        self.assertEqual("https://storage.concert.ua/poster.png", event.image_url)
        self.assertIsNone(event.price_min)
        fetch_details.assert_called_once_with(event.url, scraper.DEFAULT_TIMEOUT)

    @patch("services.concertua_pipeline._fetch_event_details")
    @patch("scrapers.concertua.ConcertuaScraper.fetch_items")
    def test_fetch_events_uses_positive_detail_price_and_never_guesses_maximum(
        self, fetch_items, fetch_details
    ):
        self.raw_item.update(priceMin=None, isFreeEntrance=False)
        fetch_items.return_value = {"items": [self.raw_item]}
        fetch_details.return_value = {
            "@type": "MusicEvent",
            "url": "https://concert.ua/uk/event/halytska-diva",
            "offers": {"price": "350", "availability": "https://schema.org/InStock"},
        }

        event = pipeline.fetch_events()[0]

        self.assertEqual(350, event.price_min)
        self.assertIsNone(event.price_max)

    @patch("services.concertua_pipeline._fetch_event_details")
    @patch("scrapers.concertua.ConcertuaScraper.fetch_items")
    def test_fetch_events_does_not_replace_listing_fields_with_details(
        self, fetch_items, fetch_details
    ):
        self.raw_item.update(description="Listing description", priceMin=250)
        fetch_items.return_value = {"items": [self.raw_item]}
        fetch_details.return_value = {
            "@type": "MusicEvent",
            "url": "https://concert.ua/uk/event/halytska-diva",
            "description": "Different detail description",
            "image": "https://storage.concert.ua/details.png",
            "offers": {"price": 350},
        }

        event = pipeline.fetch_events()[0]

        self.assertEqual("Listing description", event.description)
        self.assertEqual(250, event.price_min)
        self.assertEqual("https://storage.concert.ua/poster.png", event.image_url)

    @patch("services.concertua_pipeline._fetch_event_details")
    @patch("scrapers.concertua.ConcertuaScraper.fetch_items")
    def test_fetch_events_warns_and_keeps_listing_on_detail_failure(
        self, fetch_items, fetch_details
    ):
        self.raw_item["description"] = None
        fetch_items.return_value = {"items": [self.raw_item]}
        fetch_details.side_effect = OSError("offline")

        with self.assertWarns(RuntimeWarning):
            events = pipeline.fetch_events()

        self.assertEqual(1, len(events))
        self.assertIsNone(events[0].description)

    @patch("services.concertua_pipeline._fetch_event_details")
    @patch("scrapers.concertua.ConcertuaScraper.fetch_items")
    def test_fetch_events_can_skip_detail_requests(self, fetch_items, fetch_details):
        self.raw_item["description"] = None
        fetch_items.return_value = {"items": [self.raw_item]}

        events = pipeline.fetch_events(enrich_details=False)

        self.assertEqual(1, len(events))
        fetch_details.assert_not_called()

    @patch("services.concertua_pipeline.urlopen")
    def test_details_parser_selects_matching_event_among_other_json_ld(self, urlopen):
        matched = {
            "@type": ["Thing", "MusicEvent"],
            "url": "/uk/event/halytska-diva",
            "description": "Correct event",
        }
        graph = {"@graph": [
            {"@type": "Organization", "url": "https://concert.ua/uk/event/halytska-diva"},
            {"@type": "MusicEvent", "url": "https://concert.ua/uk/event/other", "description": "Wrong"},
            matched,
        ]}
        html = (
            '<script type="application/ld+json">invalid</script>'
            '<script type="application/ld+json; charset=utf-8">'
            + json.dumps(graph, ensure_ascii=False) + '</script>'
        )
        urlopen.return_value.__enter__.return_value = io.BytesIO(html.encode("utf-8"))

        details = pipeline._fetch_event_details("https://concert.ua/uk/event/halytska-diva", 7)

        self.assertEqual(matched, details)
        self.assertEqual(7, urlopen.call_args.kwargs["timeout"])

    @patch("services.concertua_pipeline.urlopen")
    def test_details_parser_rejects_unrelated_events(self, urlopen):
        html = '<script type="application/ld+json">' + json.dumps({
            "@type": "Event", "url": "https://concert.ua/uk/event/other",
        }) + '</script>'
        urlopen.return_value.__enter__.return_value = io.BytesIO(html.encode("utf-8"))

        with self.assertRaisesRegex(ValueError, "no matching"):
            pipeline._fetch_event_details("https://concert.ua/uk/event/halytska-diva", 7)

    @patch("services.concertua_pipeline.urlopen")
    @patch("scrapers.concertua.ConcertuaScraper.fetch_items")
    def test_fetch_events_enriches_from_realistic_page(self, fetch_items, urlopen):
        self.raw_item.update(priceMin=None, isFreeEntrance=False)
        fetch_items.return_value = {"items": [self.raw_item]}
        data = {
            "@type": "MusicEvent",
            "url": "https://concert.ua/uk/event/halytska-diva",
            "description": "Повний опис події",
            "offers": {"price": 0, "priceCurrency": "UAH"},
        }
        html = (
            '<script type></script><script type="application/ld+json">'
            + json.dumps(data, ensure_ascii=False) + '</script>'
        )
        urlopen.return_value.__enter__.return_value = io.BytesIO(html.encode("utf-8"))

        event = pipeline.fetch_events(limit=1, timeout=5)[0]

        self.assertEqual("Повний опис події", event.description)
        self.assertEqual("Театр", event.category)
        self.assertIsNone(event.price_min)
        self.assertIsNone(event.price_max)
        self.assertEqual("Concert.ua", event.source)
        self.assertEqual("https://concert.ua/uk/event/halytska-diva", event.url)
        self.assertEqual("https://storage.concert.ua/poster.png", event.image_url)
        self.assertEqual(5, urlopen.call_args.kwargs["timeout"])

    def test_detail_prices_and_missing_image_are_handled_conservatively(self):
        self.raw_item.update(priceMin=None, posterUrl=None, categoriesTitles=[], isFreeEntrance=True)
        details = {
            "genre": ["Музика", "Інше"],
            "image": [None, "/poster.png"],
            "offers": {"lowPrice": "0", "highPrice": "500", "priceCurrency": "UAH"},
        }
        event = pipeline.item_to_event(pipeline._merge_event_details(self.raw_item, details))

        self.assertEqual("Музика", event.category)
        self.assertEqual("https://concert.ua/poster.png", event.image_url)
        self.assertEqual(0, event.price_min)
        self.assertEqual(500, event.price_max)

    def test_detail_prices_ignore_sold_out_foreign_and_fractional_offers(self):
        self.raw_item["priceMin"] = None
        details = {"offers": [
            {"price": 100, "priceCurrency": "USD"},
            {"price": 100, "availability": "https://schema.org/SoldOut"},
            {"price": "100.50", "priceCurrency": "UAH"},
        ]}
        event = pipeline.item_to_event(pipeline._merge_event_details(self.raw_item, details))

        self.assertIsNone(event.price_min)
        self.assertIsNone(event.price_max)

    def test_rejects_malformed_required_fields(self):
        for field in ("title", "dateStart", "venuesTitles", "link"):
            item = dict(self.raw_item)
            item.pop(field)
            with self.subTest(field=field), self.assertRaises(pipeline.EventDataError):
                pipeline.item_to_event(item)

    @patch("scrapers.concertua.urlopen")
    def test_fetch_events_forwards_filters_and_formats_response(self, fetch_items):
        fetch_items.return_value.__enter__.return_value = io.BytesIO(
            json.dumps({"items": [self.raw_item]}).encode("utf-8")
        )

        events = pipeline.fetch_events(
            category_id=8, city_id=2, limit=12, offset=24, params={"isOnline": True},
            enrich_details=False,
        )

        self.assertEqual(1, len(events))
        self.assertEqual("Галицька Діва", events[0].title)
        query = parse_qsl(urlsplit(fetch_items.call_args.args[0].full_url).query)
        for pair in (("categoriesIds[]", "8"), ("citiesIds[]", "2"),
                     ("limit", "12"), ("offset", "24"), ("isOnline", "True")):
            self.assertIn(pair, query)
        self.assertEqual(scraper.DEFAULT_TIMEOUT, fetch_items.call_args.kwargs["timeout"])

    def test_rejects_invalid_response_structure(self):
        with self.assertRaises(pipeline.EventDataError):
            pipeline.items_to_events({"items": {}})