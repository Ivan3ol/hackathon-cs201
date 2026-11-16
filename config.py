from pathlib import Path
from zoneinfo import ZoneInfo

# Project-wide constants

BASE_DIR = Path(__file__).resolve().parent

# All event dates are stored and shown in Kyiv time
KYIV_TZ = ZoneInfo("Europe/Kyiv")

# TODO this is temporary, until we have a DB
# Events saved by main.py (manual testing only)
EVENTS_PATH = BASE_DIR / "events.json"

# How many events (cards) each scraper collects; None = all upcoming events
KARABAS_LIMIT = 100
CONCERTUA_LIMIT = 100

# How long the app keeps scraped events before scraping again
SCRAPE_TTL_SECONDS = 60 * 60
