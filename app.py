import json
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import streamlit as st

from models.event import Event

# TODO replace with actual db data later
SEED_PATH = Path(__file__).parent / "seed_events.json"

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

KYIV_TZ = ZoneInfo("Europe/Kyiv")
# TODO change this to proper calendar
PERIODS = ("Усі", "Сьогодні", "Вихідні", "Тиждень", "Свої дати")


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
        self.events = self.load_events()

    # Single entry point for UI data
    @staticmethod
    @st.cache_data(ttl=600)
    def load_events() -> list[Event]:
        data = json.loads(SEED_PATH.read_text(encoding="utf-8"))
        for item in data:
            item["start"] = datetime.fromisoformat(item["start"])
        return sorted((Event(**item) for item in data), key=lambda e: e.start)

    def run(self) -> None:
        filters = self.render_filters()
        events = EventsApp.filter_events(self.events, filters)
        self.render_header(len(events))
        EventsApp.render_events(events)

    def render_header(self, shown: int) -> None:
        st.title("Події Києва")
        st.caption(f"Знайдено подій: {shown} з {len(self.events)}")

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
                sorted({e.category for e in self.events if e.category}),
                placeholder="Усі",
                select_all=False,  # built-in "Select all" is English-only; empty = all anyway
            )
            venues = st.multiselect(
                "Майданчик",
                sorted({e.venue for e in self.events}),
                placeholder="Усі",
                select_all=False,
            )

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
            if filters.categories and event.category not in filters.categories:
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

    @staticmethod
    def render_events(events: list[Event]) -> None:
        if not events:
            st.info("Подій не знайдено.")
            return
        for event in events:
            EventsApp.render_event_card(event)

    @staticmethod
    def render_event_card(event: Event) -> None:
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
                if event.category:
                    st.badge(event.category)
                st.subheader(event.title, anchor=False)
                st.markdown(
                    f"🗓 **{EventsApp.format_date(event.start)}**  \n"
                    f"📍 {event.venue}  \n"
                    f"💰 {EventsApp.format_price(event)}"
                )
                if event.description:
                    st.caption(event.description)
                st.link_button("Детальніше", event.url)

    # "Сб, 21 листопада · 11:00"
    @staticmethod
    def format_date(start: datetime) -> str:
        weekday = WEEKDAYS[start.weekday()]
        month = MONTHS[start.month - 1]
        return f"{weekday}, {start.day} {month} · {start:%H:%M}"

    @staticmethod
    def format_price(event: Event) -> str:
        if event.price_min is None:
            return "Ціну не вказано"
        if event.price_max and event.price_max != event.price_min:
            return f"{event.price_min}–{event.price_max} грн"
        return f"від {event.price_min} грн"


if __name__ == "__main__":
    EventsApp().run()
