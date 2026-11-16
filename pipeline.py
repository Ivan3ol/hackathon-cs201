import logging
from datetime import datetime

from config import KYIV_TZ
from models.event import Event
from scrapers.base import BaseScraper

logger = logging.getLogger(__name__)


# Runs all scrapers and turns their results into one clean list of events
class Pipeline:
    def __init__(self, scrapers: list[BaseScraper]):
        self._scrapers = scrapers

    def run(self) -> list[Event]:
        collected: list[Event] = []
        for scraper in self._scrapers:
            name = type(scraper).__name__
            try:
                events = scraper.scrape()
            # TODO this should not be this broad
            except Exception:
                # one broken source must not stop the others
                logger.exception("%s failed", name)
                continue
            logger.info("%s: %d events", name, len(events))
            collected.extend(events)
        return Pipeline.process(collected, datetime.now(KYIV_TZ))

    @staticmethod
    def process(events: list[Event], now: datetime) -> list[Event]:
        unique: dict[tuple[str, str, datetime], Event] = {}
        for event in events:
            if event.start < now:
                continue
            # TODO reconsider this with real data
            # same title, venue and start time is same event
            key = (event.title.casefold(), event.venue.casefold(), event.start)
            unique.setdefault(key, event)
        return sorted(unique.values(), key=lambda e: e.start)
