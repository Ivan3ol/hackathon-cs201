from abc import ABC, abstractmethod
from models.event import Event


# Base interface that every scraper implements
class BaseScraper(ABC):
    # unique source name
    _source: str

    @property
    def source(self) -> str:
        return self._source

    # scrap based events
    @abstractmethod
    def scrape(self) -> list[Event]:
        pass
