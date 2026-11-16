import json
from datetime import datetime
from pathlib import Path

import streamlit as st

from models.event import Event

# temporary, replace with actual db data later
SEED_PATH = Path(__file__).parent / "seed_events.json"


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
        for event in events:
            st.write(f"**{event.start:%d.%m %H:%M}** · {event.title} · {event.venue}")


if __name__ == "__main__":
    EventsApp().run()
