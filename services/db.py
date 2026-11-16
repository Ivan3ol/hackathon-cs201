import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from config import DB_PATH, KYIV_TZ
from models.event import Event
from services.nbu_rates import CurrencyRate


# SQLite storage for events, the only class that talks to the database
class EventsDB:
    # primary key is Event.key (normalized title and start time)
    SCHEMA = """
    CREATE TABLE IF NOT EXISTS events (
        key         TEXT PRIMARY KEY,
        source      TEXT NOT NULL,
        title       TEXT NOT NULL,
        start       TEXT NOT NULL,
        venue       TEXT NOT NULL,
        url         TEXT NOT NULL,
        category    TEXT,
        price_min   INTEGER,
        price_max   INTEGER,
        description TEXT,
        image_url   TEXT,
        scraped_at  TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS exchange_rates (
        code         TEXT PRIMARY KEY,
        name         TEXT,
        uah_per_unit REAL NOT NULL,
        unit_per_uah REAL NOT NULL,
        fetched_at   TEXT NOT NULL
    );
    """

    # Event fields stored in the table (same names as Event properties)
    FIELDS = (
        "source",
        "title",
        "start",
        "venue",
        "url",
        "category",
        "price_min",
        "price_max",
        "description",
        "image_url",
    )

    def __init__(self, path: Path = DB_PATH):
        self._path = path

    # Replace all rows of one source with fresh events, and drop past events
    def replace_source(self, source: str, events: list[Event]) -> None:
        now = EventsDB._utc(datetime.now(UTC))
        rows = [(e.key, *(EventsDB._value(e, f) for f in self.FIELDS), now) for e in events]
        columns = ", ".join(("key", *self.FIELDS, "scraped_at"))
        placeholders = ", ".join("?" * (len(self.FIELDS) + 2))
        # one transaction: readers never see the source half-deleted
        with closing(self._connect()) as conn, conn:
            conn.execute("DELETE FROM events WHERE source = ?", (source,))
            conn.execute("DELETE FROM events WHERE start < ?", (now,))
            conn.executemany(
                f"INSERT OR IGNORE INTO events ({columns}) VALUES ({placeholders})", rows
            )

    # Upcoming events sorted by start, dates in Kyiv time
    def load_events(self) -> list[Event]:
        if not self._path.exists():
            return []
        now = EventsDB._utc(datetime.now(UTC))
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT * FROM events WHERE start >= ? ORDER BY start", (now,)
            ).fetchall()
        return [self._to_event(row) for row in rows]

    # When the most recent successful scrape happened
    def last_scraped_at(self) -> datetime | None:
        if not self._path.exists():
            return None
        with closing(self._connect()) as conn:
            value = conn.execute("SELECT MAX(scraped_at) FROM events").fetchone()[0]
        return datetime.fromisoformat(value).astimezone(KYIV_TZ) if value else None

    def load_exchange_rate(self, code: str) -> tuple[CurrencyRate, datetime] | None:
        if not self._path.exists():
            return None
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT name, uah_per_unit, unit_per_uah, fetched_at "
                "FROM exchange_rates WHERE code = ?", (code,)
            ).fetchone()
        if row is None:
            return None
        return (
            CurrencyRate(row["name"], row["uah_per_unit"], row["unit_per_uah"]),
            datetime.fromisoformat(row["fetched_at"]),
        )

    def save_exchange_rates(self, rates: dict[str, CurrencyRate]) -> None:
        now = EventsDB._utc(datetime.now(UTC))
        rows = [
            (code, rate.name, rate.uah_per_unit, rate.unit_per_uah, now)
            for code, rate in rates.items()
        ]
        with closing(self._connect()) as conn, conn:
            conn.executemany(
                "INSERT OR REPLACE INTO exchange_rates "
                "(code, name, uah_per_unit, unit_per_uah, fetched_at) VALUES (?, ?, ?, ?, ?)",
                rows,
            )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")  # readers are not blocked while scraping writes
        conn.executescript(self.SCHEMA)
        return conn

    def _to_event(self, row: sqlite3.Row) -> Event:
        values = {f: row[f] for f in self.FIELDS}
        values["start"] = datetime.fromisoformat(values["start"]).astimezone(KYIV_TZ)
        return Event(**values)

    @staticmethod
    def _value(event: Event, field: str) -> str | int | None:
        value = getattr(event, field)
        return EventsDB._utc(value) if isinstance(value, datetime) else value

    @staticmethod
    def _utc(moment: datetime) -> str:
        return moment.astimezone(UTC).isoformat()
