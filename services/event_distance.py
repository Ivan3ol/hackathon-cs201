import json
import math
import os
import re
from datetime import datetime, timedelta
from typing import Any

from models.event import Event
from services.concertua_venue_client import ConcertuaVenueClient
from services.json_ld_venue_client import JsonLdVenueClient
from services.karabas_venue_client import KarabasVenueClient
from services.nominatim_geocoder import KYIV_BBOX, NominatimGeocoder
from services.overpass_client import OverpassClient

EARTH_RADIUS_KM = 6371.0
NOT_FOUND_RETRY = timedelta(days=1)  # how long a not found venue is not searched again
VENUE_TYPE_PREFIX = re.compile(r"^(ТРЦ|ТРК|ТЦ|РЦ|КЦ|БЦ|ПК)\s+", re.I)
STREET_TYPES = re.compile(r"(?i)\b(вулиця|вул|проспект|просп|пр-т|пр|бульвар|бульв|бул|площа|пл"
                          r"|провулок|пров|узвіз|набережна|наб|шосе)\b\.?")
VENUE_KEYWORDS = ("театр", "клуб", "музей", "галерея", "паб", "pub", "студія", "кінотеатр")


# Distance (straight line) from the user's address to every event venue.
#
# Venue coordinates are searched in this order:
#   1. venue address from the event page (venue client of the event's site:
#      KarabasVenueClient, ConcertuaVenueClient) -> Nominatim, exact building
#   2. venue name -> Nominatim, exact object
#   3. venue name -> Overpass (OSM objects with this name in Kyiv; public servers are slow)
#   4. venue address -> Nominatim, approximate (e.g. middle of the street)
# Results are cached in a JSON file: found venues forever, not found ones for NOT_FOUND_RETRY.
# Coordinates are also cached by building address, so the same building under another
# venue name ("Театр на Печерську" / "Київський академічний театр на Печерську")
# is not searched again.
class EventDistanceService:
    def __init__(self, geocoder: NominatimGeocoder | None = None,
                 overpass: OverpassClient | None = None,
                 venue_clients: list[JsonLdVenueClient] | None = None,
                 cache_path: str | None = "venue_coords_cache.json"):
        self._geocoder = geocoder or NominatimGeocoder()
        self._overpass = overpass or OverpassClient()
        self._venue_clients = venue_clients or [KarabasVenueClient(), ConcertuaVenueClient()]
        self._cache_path = cache_path
        self._found: dict[str, list[float]] = {}
        self._not_found: dict[str, str] = {}  # venue -> ISO time of the last failed search
        self._addresses: dict[str, list[float]] = {}  # normalized address -> [lat, lon]
        self._load_cache()

    # [{"title": ..., "distance_km": 1.23}, ...] sorted from the nearest;
    # events whose venue was not found have distance_km = null and go last.
    def distances(self, address: str, events: list[Event]) -> list[dict[str, Any]]:
        origin = self._geocoder.geocode(address)
        if origin is None:
            raise ValueError(f"address not found: {address!r}")

        result = []
        by_venue: dict[str, float | None] = {}  # one calculation per venue, not per session
        try:
            for event in events:
                if event.venue not in by_venue:
                    venue = self.venue_coords(event)
                    by_venue[event.venue] = (round(self.haversine_km(origin, venue), 2)
                                             if venue else None)
                result.append({"title": event.title, "distance_km": by_venue[event.venue]})
        finally:
            self._save_cache()
        return sorted(result, key=lambda r: (r["distance_km"] is None, r["distance_km"] or 0))

    def venue_coords(self, event: Event) -> tuple[float, float] | None:
        venue = event.venue
        if not venue:
            return None
        if venue in self._found:
            lat, lon = self._found[venue]
            return lat, lon
        if self._recently_not_found(venue):
            return None

        coords = self._find_venue(venue, event.url)
        if coords is None:
            self._not_found[venue] = datetime.now().isoformat(timespec="seconds")
            return None
        self._not_found.pop(venue, None)
        self._found[venue] = list(coords)
        return coords

    def _recently_not_found(self, venue: str) -> bool:
        when = self._not_found.get(venue)
        if not when:
            return False
        try:
            return datetime.now() - datetime.fromisoformat(when) < NOT_FOUND_RETRY
        except ValueError:
            return False

    def _find_venue(self, venue: str, event_url: str) -> tuple[float, float] | None:
        address = self._venue_address(event_url)
        addresses = self._address_variants(address) if address else []
        key = self._address_key(addresses[-1]) if addresses else None
        if key and key in self._addresses:  # same building is already known
            lat, lon = self._addresses[key]
            return lat, lon
        names = self._name_variants(venue)

        steps = (
            [lambda a=a: self._geocoder.geocode(a, bbox=KYIV_BBOX, precise=True) for a in addresses]
            + [lambda n=n: self._geocoder.geocode(f"{n}, Київ", bbox=KYIV_BBOX, precise=True)
               for n in names]
            + [lambda n=n: self._overpass.find_place(n, KYIV_BBOX) for n in names]
            + [lambda a=a: self._geocoder.geocode(a, bbox=KYIV_BBOX) for a in addresses]
        )
        for step in steps:
            try:
                coords = step()
            except OSError:  # one failed request must not break the whole run
                coords = None
            if coords is not None:
                if key:
                    self._addresses[key] = list(coords)
                return coords
        return None

    # address from the page of the event's site (karabas, concert.ua, ...)
    def _venue_address(self, event_url: str) -> str | None:
        for client in self._venue_clients:
            if client.supports(event_url):
                return client.get_address(event_url)
        return None

    # 'вул. Велика Васильківська, 57/3, Київ' and 'Велика Васильківська 57/3' -> 'велика васильківська 57/3'
    @staticmethod
    def _address_key(address: str) -> str:
        text = re.sub(r"(?i),?\s*київ\s*$", "", address)
        text = STREET_TYPES.sub(" ", text.lower())
        text = re.sub(r"[^\w/-]+", " ", text)
        return " ".join(text.split())

    # 'Київ, вул.Немировича-Данченка, 5, Київ' -> 'вул. Немировича-Данченка, 5, Київ'
    # 'вул. Хрещатик, 7, ст.м. Майдан Незалежності, Київ' -> 'вул. Хрещатик, 7, Київ'
    # 'Верхній Вал 48/28, код від домофона 2, 2 поверх' -> 'Верхній Вал 48/28, Київ'
    # also a variant with only street + house number
    @staticmethod
    def _address_variants(address: str) -> list[str]:
        noise = re.compile(r"(?i)^(ст\.?\s*м\.?|метро|\d+\s*поверх|поверх|офіс|оф\.|корпус|вхід"
                           r"|код|домофон|київ)\b")
        text = re.sub(r"(?i)\b(вул|просп|пр|пл|бульв|бул|пров)\.(?=\S)", r"\1. ", address)
        text = re.sub(r"\bВ\.\s*Васильківська", "Велика Васильківська", text)
        parts = [p.strip() for p in text.split(",") if p.strip()]
        parts = [p for p in parts if not noise.match(p)]
        if not parts:
            return []
        street = ", ".join(parts[:2])
        return list(dict.fromkeys([f"{', '.join(parts)}, Київ", f"{street}, Київ"]))

    # 'Київська опера (Київський муніципальний театр)' -> full, without brackets, text in brackets
    # 'Арт-Студія «ТВОРЧІ», офіс 3' -> also without ', офіс 3' and quotes
    # 'РЦ БЛОКБАСТЕР' -> also 'БЛОКБАСТЕР'
    # 'Київський академічний театр "Колесо"' -> also 'театр Колесо'
    @staticmethod
    def _name_variants(venue: str) -> list[str]:
        variants = [venue.strip()]
        no_brackets = re.sub(r"\s*\(.*?\)", "", venue).strip()
        variants.append(no_brackets)
        variants.extend(m.strip() for m in re.findall(r"\((.*?)\)", venue))
        variants.append(no_brackets.split(",")[0].strip())
        variants.append(re.sub(r"[«»\"“”]", "", variants[-1]).strip())
        variants.append(VENUE_TYPE_PREFIX.sub("", variants[-1]).strip())
        quoted = re.findall(r"[«\"“](.+?)[»\"”]", venue)
        keyword = next((k for k in VENUE_KEYWORDS if k in venue.lower()), None)
        if quoted and keyword:
            variants.append(f"{keyword} {quoted[0].strip()}")
        return [v for v in dict.fromkeys(variants) if v]

    @staticmethod
    def haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
        lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
        h = (math.sin((lat2 - lat1) / 2) ** 2
             + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2)
        return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(h))

    # cache file: {"found": {venue: [lat, lon]}, "not_found": {venue: "2026-11-16T18:00:00"},
    #              "addresses": {normalized address: [lat, lon]}}
    def _load_cache(self) -> None:
        if not self._cache_path or not os.path.exists(self._cache_path):
            return
        try:
            with open(self._cache_path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return  # broken cache is just ignored
        if "found" not in data and "not_found" not in data:
            data = {"found": {k: v for k, v in data.items() if v}}  # old format
        self._found = data.get("found") or {}
        self._not_found = data.get("not_found") or {}
        self._addresses = data.get("addresses") or {}

    def _save_cache(self) -> None:
        if not self._cache_path:
            return
        with open(self._cache_path, "w", encoding="utf-8") as f:
            json.dump({"found": self._found, "not_found": self._not_found,
                       "addresses": self._addresses},
                      f, ensure_ascii=False, indent=2)
