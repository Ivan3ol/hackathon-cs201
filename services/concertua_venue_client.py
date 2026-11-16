import re

from services.json_ld_venue_client import JsonLdVenueClient


# Venue address from a concert.ua event page (schema.org JSON-LD on the page)
class ConcertuaVenueClient(JsonLdVenueClient):
    URL_PATTERN = re.compile(r"^https?://([a-z0-9-]+\.)*concert\.ua/")
