import logging
from datetime import datetime

from config import CONCERTUA_LIMIT, KARABAS_LIMIT, KYIV_TZ
from models.event import Event
from scrapers.base import BaseScraper
from scrapers.concertua import ConcertuaScraper
from scrapers.karabas import KarabasScraper

logger = logging.getLogger(__name__)


# Runs all scrapers and cleans their results,
# results are kept per source, so the DB can replace each source's rows separately,
# a source that failed is missing from the result and its old rows stay untouched
class Pipeline:
    # if two sources have the same event, the first one wins
    def __init__(self, scrapers: list[BaseScraper]):
        self._scrapers = scrapers

    # All sources used by the app, in priority order
    @classmethod
    def default(cls) -> "Pipeline":
        return cls(
            [
                KarabasScraper(limit=KARABAS_LIMIT),
                ConcertuaScraper(limit=CONCERTUA_LIMIT),
            ]
        )

    # {source: events} for every source that scraped successfully (possibly with 0 events)
    def run(self) -> dict[str, list[Event]]:
        results: dict[str, list[Event]] = {}
        for scraper in self._scrapers:
            try:
                events = scraper.scrape()
            # TODO this should not be this broad
            except Exception:
                # one broken source must not stop the others
                logger.exception("%s failed", scraper.source)
                continue
            logger.info("%s: %d events", scraper.source, len(events))
            results[scraper.source] = events
        return Pipeline.process(results, datetime.now(KYIV_TZ))

    # Drops past events and duplicates (by Event.key), within and across sources
    @staticmethod
    def process(results: dict[str, list[Event]], now: datetime) -> dict[str, list[Event]]:
        seen: set[str] = set()
        processed: dict[str, list[Event]] = {}
        for source, events in results.items():
            kept = []
            for event in events:
                if event.start < now or event.key in seen:
                    continue
                seen.add(event.key)
                kept.append(event)
            processed[source] = sorted(kept, key=lambda e: e.start)
        return processed

    # All events from all sources as one list sorted by start
    @staticmethod
    def merge(results: dict[str, list[Event]]) -> list[Event]:
        return sorted((e for events in results.values() for e in events), key=lambda e: e.start)
