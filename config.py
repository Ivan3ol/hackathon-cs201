from pathlib import Path
from zoneinfo import ZoneInfo

# Project-wide constants

BASE_DIR = Path(__file__).resolve().parent

# All event dates are stored and shown in Kyiv time
KYIV_TZ = ZoneInfo("Europe/Kyiv")

# TODO this is temporary, until we have a DB
# Events collected by main.py and shown by app.py
EVENTS_PATH = BASE_DIR / "events.json"
