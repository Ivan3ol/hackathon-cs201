from pathlib import Path
from zoneinfo import ZoneInfo

# Project-wide constants

BASE_DIR = Path(__file__).resolve().parent

# All event dates are stored and shown in Kyiv time
KYIV_TZ = ZoneInfo("Europe/Kyiv")

# SQLite database with collected events
DB_PATH = BASE_DIR / "events.db"

# Events saved by main.py (manual testing only)
EVENTS_PATH = BASE_DIR / "events.json"

# How many events each scraper collects, None -> all upcoming events
KARABAS_LIMIT = 100
# Karabas counts single shows, Concert.ua counts different events with all their shows
CONCERTUA_LIMIT = 100

# How old the data in the DB may be before the app scrapes again
SCRAPE_TTL_SECONDS = 60 * 60

# UI

# Ukrainian names
WEEKDAYS = ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Нд")
MONTHS = (
    "січня",
    "лютого",
    "березня",
    "квітня",
    "травня",
    "червня",
    "липня",
    "серпня",
    "вересня",
    "жовтня",
    "листопада",
    "грудня",
)

UA_ALPHABET = "абвгґдеєжзиіїйклмнопрстуфхцчшщьюя"
CACHE_TTL_SECONDS = 600  # how often the app re-reads the DB
PAGE_SIZE = 25  # events per page
DESCRIPTION_PREVIEW = 200  # chars of description shown in a card before "Повний опис"
# TODO change this to proper calendar
PERIODS = ("Усі", "Сьогодні", "Вихідні", "Тиждень", "Свої дати")
