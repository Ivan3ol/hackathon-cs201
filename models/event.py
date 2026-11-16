import re
from datetime import UTC, datetime


# Base model for events to be scrapped and displayed.
class Event:
    def __init__(
        self,
        title: str,
        start: datetime,
        venue: str,
        url: str,
        source: str,
        category: str | None = None,
        price_min: int | None = None,
        price_max: int | None = None,
        description: str | None = None,
        image_url: str | None = None,
    ):
        # naive datetimes are not allowed: always Europe/Kyiv
        if start.tzinfo is None:
            raise ValueError(f"start must be timezone-aware, got {start!r}")

        self.__title = title
        self.__start = start
        self.__venue = venue
        self.__url = url
        self.__source = source
        self.__category = category
        self.__price_min = price_min  # UAH
        self.__price_max = price_max  # UAH
        self.__description = description
        self.__image_url = image_url  # poster, absolute URL

    @property
    def title(self) -> str:
        return self.__title

    @property
    def start(self) -> datetime:
        return self.__start

    @property
    def venue(self) -> str:
        return self.__venue

    @property
    def url(self) -> str:
        return self.__url

    @property
    def source(self) -> str:
        return self.__source

    @property
    def category(self) -> str | None:
        return self.__category

    @property
    def price_min(self) -> int | None:
        return self.__price_min

    @property
    def price_max(self) -> int | None:
        return self.__price_max

    @property
    def description(self) -> str | None:
        return self.__description

    @property
    def image_url(self) -> str | None:
        return self.__image_url

    # Identity of an event across all sources - normalized title and start time
    @property
    def key(self) -> str:
        title = re.sub(r"\W+", "", self.__title.casefold())
        return f"{title}|{self.__start.astimezone(UTC).isoformat()}"

    def to_dict(self) -> dict[str, str | int | None]:
        return {
            "title": self.__title,
            "start": self.__start.isoformat(),
            "venue": self.__venue,
            "url": self.__url,
            "source": self.__source,
            "category": self.__category,
            "price_min": self.__price_min,
            "price_max": self.__price_max,
            "description": self.__description,
            "image_url": self.__image_url,
        }

    def __repr__(self) -> str:
        return f"Event({self.to_dict()!r})"
