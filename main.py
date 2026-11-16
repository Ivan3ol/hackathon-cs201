from scrapers.karabas import KarabasScraper
from services.json_exporter import save_json

# how many events (cards) to scrape; None = all upcoming events
KARABAS_LIMIT = 100


def main() -> None:
    print("Події Києва")

    events = KarabasScraper(limit=KARABAS_LIMIT).scrape()
    save_json(events, "karabas_events.json")


if __name__ == "__main__":
    main()
