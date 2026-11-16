import re
import sqlite3
from dataclasses import astuple, dataclass, field
from datetime import date, datetime, timedelta

import streamlit as st

from config import (
    CACHE_TTL_SECONDS,
    DESCRIPTION_PREVIEW,
    KYIV_TZ,
    MONTHS,
    PAGE_SIZE,
    PERIODS,
    SCRAPE_TTL_SECONDS,
    UA_ALPHABET,
    WEEKDAYS,
)
from models.event import Event
from pipeline import Pipeline
from services.db import EventsDB
from services.event_distance import EventDistanceService
from services.nbu_rates import NbuRatesService


# Current filter values from the sidebar
@dataclass
class Filters:
    query: str = ""
    date_from: date | None = None
    date_to: date | None = None
    categories: list[str] = field(default_factory=list)
    venues: list[str] = field(default_factory=list)


# Streamlit dashboard
class EventsApp:
    def __init__(self) -> None:
        st.set_page_config(page_title="Події Києва", layout="wide")
        self.events, self.updated_at = self.load_events()
        self.currency = st.session_state.get("currency", "UAH")
        self.exchange_rate = None
        self.address = ""  # user's address from the sidebar, set in render_filters

    # returns (events, when the data was scraped; None if nothing was ever scraped)
    @staticmethod
    @st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner="Збираємо події з афіш…")
    def load_events() -> tuple[list[Event], datetime | None]:
        database = EventsDB()
        updated_at = database.last_scraped_at()
        if updated_at is None or datetime.now(KYIV_TZ) - updated_at > timedelta(
            seconds=SCRAPE_TTL_SECONDS
        ):
            # scrapes again only if the DB is empty or older than SCRAPE_TTL_SECONDS
            EventsApp.refresh_database(database)
            updated_at = database.last_scraped_at()

        return database.load_events(), updated_at

    # Scrapes all sources and writes them to the DB; the first source written wins on duplicates
    @staticmethod
    def refresh_database(database: EventsDB) -> None:
        for source, events in Pipeline.default().run().items():
            database.replace_source(source, events)

    # "Оновити зараз" button: scrape right away, ignoring SCRAPE_TTL_SECONDS
    @staticmethod
    def force_refresh() -> None:
        with st.spinner("Збираємо події з афіш…"):
            EventsApp.refresh_database(EventsDB())
        EventsApp.load_events.clear()  # drop cached events so the page reads the fresh DB
        st.rerun()

    @staticmethod
    def load_exchange_rate(currency: str) -> float:
        database = EventsDB()
        cached = database.load_exchange_rate(currency)
        if cached is not None and datetime.now(KYIV_TZ) - cached[1] < timedelta(hours=1):
            return cached[0].uah_per_unit
        rates = NbuRatesService().get_rates()
        database.save_exchange_rates(rates)
        return rates[currency].uah_per_unit

    def run(self) -> None:
        filters = self.render_filters()
        # filters work on single shows, then shows of the same event become one card
        events = EventsApp.filter_events(self.events, filters)
        groups = EventsApp.group_shows(events)
        self.render_header(len(groups), len(events))

        page, pages = EventsApp.current_page(filters, len(groups))
        first = (page - 1) * PAGE_SIZE
        EventsApp.render_pagination(page, pages, "top")
        self.render_events(groups[first : first + PAGE_SIZE])
        EventsApp.render_pagination(page, pages, "bottom")

    def render_header(self, shown_events: int, shown_shows: int) -> None:
        st.markdown(
            '<style>[data-testid="stPopoverBody"] { min-width: 0; width: max-content; }</style>',
            unsafe_allow_html=True,
        )
        title, currency = st.columns([5, 1])
        with title:
            st.title("Події Києва")
        with currency:
            with st.popover(f"Валюта: {self.currency}"):
                for code in ("UAH", "USD", "GBP", "EUR"):
                    if st.button(code, key=f"currency_{code}"):
                        st.session_state["currency"] = code
                        st.rerun()
        self.exchange_rate = None
        if self.currency != "UAH":
            try:
                self.exchange_rate = self.load_exchange_rate(self.currency)
            except (OSError, ValueError, KeyError, sqlite3.Error) as exc:
                st.error(f"Не вдалося завантажити курс валют: {exc}")
        if self.updated_at is None:
            # DB is empty and every source failed
            st.warning("Не вдалося зібрати події з афіш. Спробуйте пізніше.")
        total = len(EventsApp.group_shows(self.events))
        caption = f"Знайдено подій: {shown_events} з {total}"
        if shown_shows != shown_events:
            word = EventsApp.plural(shown_shows, ("показ", "покази", "показів"))
            caption += f" ({shown_shows} {word})"
        if self.updated_at:
            caption += f" · оновлено {EventsApp.format_date(self.updated_at)}"
        with st.container(horizontal=True, vertical_alignment="center"):
            st.caption(caption)
            if st.button("🔄 Оновити зараз", help="Зібрати події з афіш заново (≈ 30–40 с)"):
                EventsApp.force_refresh()

    # Sidebar filter
    def render_filters(self) -> Filters:
        with st.sidebar:
            st.header("Фільтри")
            query = st.text_input("Пошук", placeholder="Назва або майданчик", live=True)

            period = st.radio("Коли", PERIODS)
            date_from, date_to = EventsApp.period_range(period, datetime.now(KYIV_TZ).date())
            if period == "Свої дати":
                picked = st.date_input("Дати", value=(), format="DD.MM.YYYY")
                if picked and len(picked) == 2:
                    date_from, date_to = picked

            categories = st.multiselect(
                "Категорія",
                sorted(
                    {c for e in self.events for c in EventsApp.categories_of(e)},
                    key=EventsApp.ua_sort_key,
                ),
                placeholder="Усі",
                select_all=False,  # built-in "Select all" is English-only; empty = all anyway
            )
            venues = st.multiselect(
                "Майданчик",
                sorted({e.venue for e in self.events}, key=EventsApp.ua_sort_key),
                placeholder="Усі",
                select_all=False,
            )

            # not a filter: used by "Розрахувати відстань" on event cards
            self.address = st.text_input(
                "Ваша адреса", placeholder="Вулиця та номер будинку", live=True
            ).strip()

        return Filters(query.strip(), date_from, date_to, categories, venues)

    # Date bounds (inclusive) for a quick period; None means "no limit"
    @staticmethod
    def period_range(period: str, today: date) -> tuple[date | None, date | None]:
        # TODO change this from string to enum
        if period == "Сьогодні":
            return today, today
        if period == "Вихідні":
            # current weekend if today is Sat/Sun, otherwise the next one
            if today.weekday() == 6:
                saturday = today - timedelta(days=1)
            else:
                saturday = today + timedelta(days=5 - today.weekday())
            return saturday, saturday + timedelta(days=1)
        if period == "Тиждень":
            return today, today + timedelta(days=6)
        return None, None

    @staticmethod
    def filter_events(events: list[Event], filters: Filters) -> list[Event]:
        query = filters.query.casefold()
        result = []
        for event in events:
            day = event.start.astimezone(KYIV_TZ).date()
            if filters.date_from and day < filters.date_from:
                continue
            if filters.date_to and day > filters.date_to:
                continue
            # match if the event has at least one of the selected categories
            if filters.categories and not set(EventsApp.categories_of(event)) & set(
                filters.categories
            ):
                continue
            if filters.venues and event.venue not in filters.venues:
                continue
            if (
                query
                and query not in event.title.casefold()
                and query not in event.venue.casefold()
            ):
                continue
            result.append(event)
        return result

    def render_events(self, groups: list[list[Event]]) -> None:
        if not groups:
            st.info("Подій не знайдено.")
            return
        for shows in groups:
            self.render_event_card(shows)

    # Shows of the same event (same title and venue) in one list
    @staticmethod
    def group_shows(events: list[Event]) -> list[list[Event]]:
        groups: dict[tuple[str, str], list[Event]] = {}
        for event in events:
            key = (re.sub(r"\W+", "", event.title.casefold()), event.venue.casefold())
            groups.setdefault(key, []).append(event)
        # events come sorted by start, so groups are ordered by their next show
        return list(groups.values())

    # Current page (1-based) and number of pages, goes back to page 1 when filters change
    @staticmethod
    def current_page(filters: Filters, total: int) -> tuple[int, int]:
        pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
        # compare plain values, since two Filters objects are never equal
        values = astuple(filters)
        if st.session_state.get("filters") != values:
            st.session_state["filters"] = values
            st.session_state["page"] = 1
        page = min(max(st.session_state.get("page", 1), 1), pages)
        st.session_state["page"] = page
        return page, pages

    # position - "top" or "bottom", makes widget keys unique
    @staticmethod
    def render_pagination(page: int, pages: int, position: str) -> None:
        if pages <= 1:
            return
        prev_col, info_col, next_col = st.columns([1, 2, 1], vertical_alignment="center")
        prev_col.button(
            "← Попередня",
            key=f"prev_{position}",
            disabled=page <= 1,
            on_click=EventsApp.go_to_page,
            args=(page - 1,),
            width="stretch",
        )
        info_col.markdown(
            f"<div style='text-align:center'>Сторінка {page} з {pages}</div>",
            unsafe_allow_html=True,
        )
        next_col.button(
            "Наступна →",
            key=f"next_{position}",
            disabled=page >= pages,
            on_click=EventsApp.go_to_page,
            args=(page + 1,),
            width="stretch",
        )

    # button callback: runs before the rerun, so the new page is rendered right away
    @staticmethod
    def go_to_page(page: int) -> None:
        st.session_state["page"] = page

    # One card per event, shows - all its (filtered) shows, the first one is the nearest
    def render_event_card(self, shows: list[Event]) -> None:
        event = shows[0]
        with st.container(border=True):
            poster, info = st.columns([1, 5], gap="medium")
            with poster:
                if event.image_url:
                    st.image(event.image_url, width="stretch")
                else:
                    st.markdown(
                        "<div style='font-size:4rem;text-align:center'>🎭</div>",
                        unsafe_allow_html=True,
                    )
            with info:
                categories = EventsApp.categories_of(event)
                if categories:
                    # all badges in one line
                    st.markdown(" ".join(f":blue-badge[{c}]" for c in categories))
                st.subheader(event.title, anchor=False)
                st.markdown(
                    f"🗓 **{EventsApp.format_date(event.start)}**"
                    f"{EventsApp.more_dates(shows)}  \n"
                    f"📍 {event.venue}  \n"
                    f"💰 {self.format_price(event)}"
                )
                if event.description:
                    EventsApp.render_description(event.description)
                if len(shows) > 1:
                    with st.expander(f"Усі дати ({len(shows)})"):
                        st.markdown(
                            "\n".join(
                                f"- [{EventsApp.format_date(s.start)}]({s.url})" for s in shows
                            )
                        )
                with st.container(horizontal=True):
                    st.link_button("Детальніше", event.url)
                    clicked = st.button(
                        "📏 Розрахувати відстань",
                        key=f"distance_{event.key}",
                        disabled=not self.address,
                        help=None if self.address else "Спершу введіть адресу в бічній панелі",
                    )
                if clicked:
                    self.calculate_distance(event)
                self.render_distance(event)

    # Distance from the user's address to the event venue, saved in session_state
    # so it stays on the card after the next rerun
    def calculate_distance(self, event: Event) -> None:
        with st.spinner("Рахуємо відстань…"):
            try:
                result = EventDistanceService().distances(self.address, [event])
            except ValueError:  # the service could not find the user's address
                st.warning("Не вдалося знайти вашу адресу. Перевірте, як вона написана.")
                return
            except OSError:
                st.error("Не вдалося розрахувати відстань. Спробуйте пізніше.")
                return
        distances = st.session_state.setdefault("distances", {})
        distances[(self.address, event.venue)] = result[0]["distance_km"]

    def render_distance(self, event: Event) -> None:
        distances = st.session_state.get("distances", {})
        key = (self.address, event.venue)
        if key not in distances:
            return
        km = distances[key]
        if km is None:
            st.caption("📏 Не вдалося знайти майданчик на мапі")
        else:
            st.markdown(f"📏 **≈ {EventsApp.format_distance(km)}** від вашої адреси (по прямій)")

    # 0.85 -> "850 м", 3.24 -> "3,2 км"
    @staticmethod
    def format_distance(km: float) -> str:
        meters = round(km * 1000, -1)
        if meters < 1000:
            return f"{meters:.0f} м"
        return f"{km:.1f} км".replace(".", ",")

    # " · ще 54 дати, до 10 січня" for an event with several shows, "" otherwise
    @staticmethod
    def more_dates(shows: list[Event]) -> str:
        more = len(shows) - 1
        if more == 0:
            return ""
        last = shows[-1].start
        word = EventsApp.plural(more, ("дата", "дати", "дат"))
        return f" · ще {more} {word}, до {last.day} {MONTHS[last.month - 1]}"

    # Ukrainian plural form: 1 дата, 2 дати, 5 дат, 11 дат, 21 дата
    @staticmethod
    def plural(n: int, forms: tuple[str, str, str]) -> str:
        if n % 10 == 1 and n % 100 != 11:
            return forms[0]
        if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
            return forms[1]
        return forms[2]

    # Event.category may hold several categories
    @staticmethod
    def categories_of(event: Event) -> list[str]:
        if not event.category:
            return []
        return [c.strip() for c in event.category.split(",") if c.strip()]

    # Ukrainian alphabetical order, Latin goes first
    @staticmethod
    def ua_sort_key(text: str) -> list[int]:
        return [
            1000 + UA_ALPHABET.index(ch) if ch in UA_ALPHABET else ord(ch) for ch in text.casefold()
        ]

    # Short preview, the full text is in a collapsed block
    @staticmethod
    def render_description(text: str) -> None:
        if len(text) <= DESCRIPTION_PREVIEW:
            st.caption(text)
            return
        preview = text[:DESCRIPTION_PREVIEW].rsplit(" ", 1)[0]  # cut at a word boundary
        st.caption(preview + "…")
        with st.expander("Повний опис"):
            st.caption(text)

    # "Сб, 21 листопада · 11:00"
    @staticmethod
    def format_date(start: datetime) -> str:
        weekday = WEEKDAYS[start.weekday()]
        month = MONTHS[start.month - 1]
        return f"{weekday}, {start.day} {month} · {start:%H:%M}"

    def format_price(self, event: Event) -> str:
        if event.price_min is None:
            return "Ціну не вказано"
        if self.currency != "UAH":
            if self.exchange_rate is None:
                return "Курс валюти недоступний"
            minimum = event.price_min / self.exchange_rate
            if event.price_max and event.price_max != event.price_min:
                maximum = event.price_max / self.exchange_rate
                return f"{minimum:.2f}–{maximum:.2f} {self.currency}"
            return f"від {minimum:.2f} {self.currency}"
        if event.price_max and event.price_max != event.price_min:
            return f"{event.price_min}–{event.price_max} грн"
        return f"від {event.price_min} грн"


if __name__ == "__main__":
    EventsApp().run()
