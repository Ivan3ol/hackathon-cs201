import json
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any


@dataclass(frozen=True)
class CurrencyRate:
    name: str | None
    uah_per_unit: float
    unit_per_uah: float

    def to_dict(self) -> dict[str, str | float | None]:
        return {
            "name": self.name,
            "uah_per_unit": self.uah_per_unit,
            "unit_per_uah": self.unit_per_uah,
        }


# Official UAH exchange rates from the National Bank of Ukraine (bank.gov.ua)
class NbuRatesService:
    API_URL = "https://bank.gov.ua/NBUStatService/v1/statdirectory/exchange"
    DEFAULT_CURRENCIES = ("USD", "EUR", "GBP")

    def __init__(self, currencies: tuple[str, ...] = DEFAULT_CURRENCIES, timeout: float = 30.0):
        self._currencies = tuple(c.upper() for c in currencies)
        self._timeout = timeout
        self._rate_date: str | None = None

    # Rates for the given day (today if None), keyed by currency code.
    def get_rates(self, on_date: date | None = None) -> dict[str, CurrencyRate]:
        rates: dict[str, CurrencyRate] = {}
        rate_date: str | None = None

        for item in self._fetch(on_date):
            code = item.get("cc")
            raw_rate = item.get("rate")
            if code not in self._currencies or raw_rate is None or raw_rate == "":
                continue
            rate = float(raw_rate)
            if rate == 0:
                continue
            rates[code] = CurrencyRate(
                name=item.get("txt"),
                uah_per_unit=rate,
                unit_per_uah=round(1 / rate, 6),
            )
            rate_date = rate_date or self._iso_date(item.get("exchangedate"))

        missing = [c for c in self._currencies if c not in rates]
        if missing:
            raise ValueError(f"NBU returned no rates for: {', '.join(missing)}")

        self._rate_date = rate_date
        return {code: rates[code] for code in self._currencies}

    def save_json(self, path: str, on_date: date | None = None) -> dict[str, Any]:
        data = self.get_rates(on_date)
        export = {
            "date": self._rate_date,
            "source": "bank.gov.ua",
            "rates": {code: rate.to_dict() for code, rate in data.items()},
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(export, f, ensure_ascii=False, indent=2)
        return export

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
