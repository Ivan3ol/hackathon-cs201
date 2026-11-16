from enum import Enum


# Fields of the Event model and their names in every source API.
#
#   key        - name of the field in Event and in the output JSON
#   karabas    - field name in kyiv.karabas.com API (/api/catalog/events)
#   concert_ua - field name in concert.ua API (/api/v3/items)
#
# None means the source has no such field.
class EventField(Enum):
    TITLE = ("title", "name", "title")
    START = ("start", "event_date", "dateStart")
    VENUE = ("venue", "building_name", "venuesTitles")
    URL = ("url", "event_url", "link")
    SOURCE = ("source", None, None)
    CATEGORY = ("category", "category", "categoriesTitles")
    PRICE_MIN = ("price_min", "price_from", "priceMin")
    PRICE_MAX = ("price_max", "price_to", None)
    DESCRIPTION = ("description", "description", None)
    IMAGE_URL = ("image_url", "image_big", "posterUrl")

    def __init__(self, key: str, karabas: str | None, concert_ua: str | None):
        self.key = key
        self.karabas = karabas
        self.concert_ua = concert_ua
