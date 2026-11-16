import json
import urllib.request
from datetime import date, datetime
from typing import Any


# Official UAH exchange rates from the National Bank of Ukraine (bank.gov.ua)
class NbuRatesService:
    API_URL = "https://bank.gov.ua/NBUStatService/v1/statdirectory/exchange"
    DEFAULT_CURRENCIES = ("USD", "EUR", "GBP")

    def __init__(self, currencies: tuple[str, ...] = DEFAULT_CURRENCIES, timeout: float = 30.0):
        self._currencies = tuple(c.upper() for c in currencies)
        self._timeout = timeout

    # Rates for the given day (today if None).
    # {
    #   "date": "2026-11-17",
    #   "source": "bank.gov.ua",
    #   "rates": {
    #     "USD": {"name": "Долар США", "uah_per_unit": 45.3918, "unit_per_uah": 0.022030}, ...
    #   }
    # }
    def get_rates(self, on_date: date | None = None) -> dict[str, Any]:
        rates: dict[str, Any] = {}
        rate_date: str | None = None

        for item in self._fetch(on_date):
            code = item.get("cc")
            if code not in self._currencies or not item.get("rate"):
                continue
            rate = float(item["rate"])
            rates[code] = {
                "name": item.get("txt"),
                "uah_per_unit": rate,               # 1 USD = 45.39 UAH
                "unit_per_uah": round(1 / rate, 6),  # 1 UAH = 0.022 USD
            }
            rate_date = rate_date or self._iso_date(item.get("exchangedate"))

        missing = [c for c in self._currencies if c not in rates]
        if missing:
            raise ValueError(f"NBU returned no rates for: {', '.join(missing)}")

        return {
            "date": rate_date,
            "source": "bank.gov.ua",
            "rates": {code: rates[code] for code in self._currencies},
        }

    def _fetch(self, on_date: date | None) -> list[dict[str, Any]]:
        url = f"{self.API_URL}?json"
        if on_date is not None:
            url += f"&date={on_date:%Y%m%d}"
        request = urllib.request.Request(url, headers={
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0",  # NBU returns 403 for custom user agents
        })
        with urllib.request.urlopen(request, timeout=self._timeout) as response:
            return json.load(response)

    # "17.11.2026" -> "2026-11-17"
    @staticmethod
    def _iso_date(value: str | None) -> str | None:
        if not value:
            return None
        return datetime.strptime(value, "%d.%m.%Y").date().isoformat()
