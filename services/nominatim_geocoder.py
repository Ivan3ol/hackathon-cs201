import json
import time
import urllib.error
import urllib.parse
import urllib.request

# (south, west, north, east)
KYIV_BBOX = (50.21, 30.23, 50.60, 30.83)

# Result types that are only an approximate location (a whole street, district...)
APPROXIMATE_TYPES = {
    "road", "street", "pedestrian", "residential", "neighbourhood", "quarter", "suburb",
    "city_district", "borough", "city", "town", "village", "county", "state", "postcode",
}


# Address / place name -> coordinates via OpenStreetMap Nominatim.
# Usage policy: max 1 request per second, meaningful User-Agent.
class NominatimGeocoder:
    API_URL = "https://nominatim.openstreetmap.org/search"
    MIN_INTERVAL = 1.1  # seconds between requests
    RETRIES = 2         # extra attempts on 5xx / timeouts

    def __init__(self, user_agent: str = "kyiv-events-hackathon/1.0", timeout: float = 20.0):
        self._user_agent = user_agent
        self._timeout = timeout
        self._last_request = 0.0

    # Returns (lat, lon) or None if nothing was found.
    # bbox      - limit results to an area, e.g. KYIV_BBOX
    # precise   - only exact objects (building, venue), not a whole street / district
    def geocode(self, query: str, bbox: tuple[float, float, float, float] | None = None,
                precise: bool = False) -> tuple[float, float] | None:
        params = {"q": query, "format": "jsonv2", "limit": 1, "countrycodes": "ua"}
        if bbox is not None:
            south, west, north, east = bbox
            params["viewbox"] = f"{west},{north},{east},{south}"
            params["bounded"] = 1

        results = self._request(params)
        if not results:
            return None
        best = results[0]
        if precise and (best.get("category") == "highway"
                        or best.get("addresstype") in APPROXIMATE_TYPES):
            return None
        return float(best["lat"]), float(best["lon"])

    def _request(self, params: dict) -> list[dict]:
        url = f"{self.API_URL}?{urllib.parse.urlencode(params)}"
        headers = {"User-Agent": self._user_agent, "Accept-Language": "uk"}
        for attempt in range(self.RETRIES + 1):
            self._wait()
            try:
                request = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(request, timeout=self._timeout) as response:
                    return json.load(response)
            except urllib.error.HTTPError as error:
                if error.code < 500 or attempt == self.RETRIES:
                    raise
            except (TimeoutError, urllib.error.URLError):
                if attempt == self.RETRIES:
                    raise
            time.sleep(2 * (attempt + 1))
        return []

    def _wait(self) -> None:
        pause = self.MIN_INTERVAL - (time.monotonic() - self._last_request)
        if pause > 0:
            time.sleep(pause)
        self._last_request = time.monotonic()
