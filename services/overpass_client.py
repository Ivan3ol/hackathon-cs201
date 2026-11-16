import json
import time
import urllib.parse
import urllib.request


# Search of OpenStreetMap objects via Overpass API.
# Public Overpass servers are often overloaded, so several endpoints are tried
# with a short timeout, and after MAX_FAILURES failed requests in a row the
# client switches itself off (find_place returns None) to not slow down callers.
class OverpassClient:
    ENDPOINTS = (
        "https://overpass-api.de/api/interpreter",
        "https://overpass.kumi.systems/api/interpreter",
    )
    MAX_FAILURES = 2
    MIN_INTERVAL = 1.0  # seconds between requests, to be polite to public servers
    NAME_TAGS = ("name", "name:uk", "alt_name", "official_name", "short_name")

    def __init__(self, endpoints: tuple[str, ...] = ENDPOINTS, timeout: float = 8.0,
                 user_agent: str = "kyiv-events-hackathon/1.0"):
        self._endpoints = endpoints
        self._timeout = timeout
        self._user_agent = user_agent
        self._failures = 0
        self._last_request = 0.0

    @property
    def available(self) -> bool:
        return self._failures < self.MAX_FAILURES

    # Object with exactly this name inside bbox (south, west, north, east) -> (lat, lon)
    def find_place(self, name: str,
                   bbox: tuple[float, float, float, float]) -> tuple[float, float] | None:
        if not self.available:
            return None

        value = name.replace("\\", "\\\\").replace('"', '\\"')
        box = ",".join(str(x) for x in bbox)
        union = "".join(f'nwr["{tag}"="{value}"]({box});' for tag in self.NAME_TAGS)
        query = f"[out:json][timeout:{int(self._timeout)}];({union});out center 1;"

        elements = self._run(query)
        if not elements:
            return None
        element = elements[0]
        center = element.get("center") or element
        if "lat" not in center:
            return None
        return float(center["lat"]), float(center["lon"])

    def _run(self, query: str) -> list[dict] | None:
        body = urllib.parse.urlencode({"data": query}).encode()
        for endpoint in self._endpoints:
            request = urllib.request.Request(endpoint, data=body,
                                             headers={"User-Agent": self._user_agent})
            self._wait()
            try:
                with urllib.request.urlopen(request, timeout=self._timeout) as response:
                    elements = json.load(response).get("elements", [])
                self._failures = 0
                return elements
            except (OSError, ValueError):  # network errors, timeouts, 5xx, bad JSON
                self._failures += 1
                if not self.available:
                    return None
        return None

    def _wait(self) -> None:
        pause = self.MIN_INTERVAL - (time.monotonic() - self._last_request)
        if pause > 0:
            time.sleep(pause)
        self._last_request = time.monotonic()
