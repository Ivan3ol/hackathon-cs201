import re

from services.json_ld_venue_client import JsonLdVenueClient


# Venue address from a karabas.com event page (schema.org JSON-LD on the page)
class KarabasVenueClient(JsonLdVenueClient):
    URL_PATTERN = re.compile(r"^https?://([a-z0-9-]+\.)*karabas\.com/")
