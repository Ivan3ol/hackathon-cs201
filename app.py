import json
from datetime import datetime
from pathlib import Path

import streamlit as st

from models.event import Event

# temporary, replace with actual db data later
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
        self.render_header()
        EventsApp.render_events(self.events)

    def render_header(self) -> None:
        st.title("Події Києва")
        st.caption(f"Подій: {len(self.events)}")

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
