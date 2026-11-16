import json
import re
import urllib.request
from typing import Any


# Base client: venue address from an event page with schema.org JSON-LD:
#   {"@type": "...Event", "location": {"@type": "Place", "name": "...",
#       "address": {"streetAddress": "Андріївський узвіз, 20-Б", "addressLocality": "Київ"}}}
# Subclasses set URL_PATTERN - which site's pages they handle.
class JsonLdVenueClient:
    URL_PATTERN: re.Pattern = re.compile(r"^$")
    JSON_LD = re.compile(r"<script[^>]*application/ld\+json[^>]*>(.*?)</script>", re.S | re.I)
    USER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

    def __init__(self, timeout: float = 20.0):
        self._timeout = timeout

    def supports(self, event_url: str) -> bool:
        return bool(self.URL_PATTERN.match(event_url or ""))

    # "Андріївський узвіз, 20-Б, Київ" or None (other site / page unavailable / no address)
    def get_address(self, event_url: str) -> str | None:
        if not self.supports(event_url):
            return None
        try:
            page = self._fetch(event_url)
        except OSError:
            return None

        for block in self.JSON_LD.findall(page):
            try:
                data = json.loads(block)
            except ValueError:
                continue
            address = self._address(self._find_place(data))
            if address:
                return address
        return None

    @staticmethod
    def _address(place: dict | None) -> str | None:
        if not place:
            return None
        address = place.get("address")
        if isinstance(address, str):
            return address.strip() or None
        if not isinstance(address, dict):
            return None
        street = (address.get("streetAddress") or "").strip()
        if not street:
            return None
        city = (address.get("addressLocality") or "").strip()
        return f"{street}, {city}" if city else street

    # "location" of the first Event node (MusicEvent, TheaterEvent, ...) with a street address.
    # Only event locations are used: other Places on the page are not the venue, e.g.
    # concert.ua's Organization block lists its ticket offices ("hasPOS") with addresses.
    def _find_place(self, data: Any) -> dict | None:
        if isinstance(data, dict):
            if self._is_event(data):
                locations = data.get("location")
                for place in locations if isinstance(locations, list) else [locations]:
                    if isinstance(place, dict) and self._address(place):
                        return place
            values = [v for k, v in data.items() if k != "hasPOS"]
        elif isinstance(data, list):
            values = data
        else:
            return None
        for value in values:
            found = self._find_place(value)
            if found:
                return found
        return None

    @staticmethod
    def _is_event(node: dict) -> bool:
        types = node.get("@type")
        types = types if isinstance(types, list) else [types]
        return any(isinstance(t, str) and t.endswith("Event") for t in types)

    def _fetch(self, url: str) -> str:
        request = urllib.request.Request(url, headers={
            "User-Agent": self.USER_AGENT,
            "Accept": "text/html",
            "Accept-Language": "uk",
        })
        with urllib.request.urlopen(request, timeout=self._timeout) as response:
            return response.read().decode("utf-8", errors="replace")
