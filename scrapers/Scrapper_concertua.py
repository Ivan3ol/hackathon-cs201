"""Fetch raw event data from the Concert.ua API."""

import argparse
import json
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen


API_URL = (
    "https://concert.ua/api/v3/items?citiesIds[]=1&language=uk&limit=24"
    "&offset=0&sortType=sort_by_popularity"
)
DEFAULT_TIMEOUT = 15


class APIError(RuntimeError):
    """Raised when the API cannot provide a valid JSON response."""


def _has_query_values(value):
    if value is None:
        return False
    if isinstance(value, (list, tuple)):
        return any(item is not None and item != "" for item in value)
    return value != ""


def build_items_url(
    url=API_URL,
    *,
    category_ids=None,
    city_ids=None,
    language=None,
    limit=None,
    offset=None,
    sort_type=None,
    params=None,
):
    """Build an API URL, preserving existing query values unless overridden."""
    replacements = {}
    for key, value in (
        ("categoriesIds[]", category_ids),
        ("citiesIds[]", city_ids),
        ("language", language),
        ("limit", limit),
        ("offset", offset),
        ("sortType", sort_type),
    ):
        if _has_query_values(value):
            replacements[key] = value

    for key, value in (params or {}).items():
        if _has_query_values(value):
            replacements[key] = value

    parts = urlsplit(url)
    query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key not in replacements
    ]
    for key, value in replacements.items():
        values = value if isinstance(value, (list, tuple)) else [value]
        for item in values:
            if item is None or item == "":
                continue
            query.append((key, str(item)))

    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment)
    )


def fetch_items(
    url=API_URL,
    timeout=DEFAULT_TIMEOUT,
    *,
    category_ids=None,
    city_ids=None,
    language=None,
    limit=None,
    offset=None,
    sort_type=None,
    params=None,
):
    """Return the API's decoded JSON response without transforming its data."""
    request = Request(
        build_items_url(
            url,
            category_ids=category_ids,
            city_ids=city_ids,
            language=language,
            limit=limit,
            offset=offset,
            sort_type=sort_type,
            params=params,
        ),
        headers={
            "Accept": "application/json",
            "Accept-Language": "uk,en-US;q=0.9,en;q=0.8",
            "User-Agent": "Mozilla/5.0",
        },
    )

    try:
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        raise APIError(f"API request failed with HTTP {error.code}") from error
    except URLError as error:
        raise APIError(f"API request failed: {error.reason}") from error
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise APIError("API response was not valid UTF-8 JSON") from error
    except TimeoutError as error:
        raise APIError("API request timed out") from error


def fetch(
    category_id=None,
    city_id=None,
    limit=None,
    offset=None,
    *,
    language=None,
    sort_type=None,
    timeout=DEFAULT_TIMEOUT,
    params=None,
):
    """Fetch raw JSON using convenient singular category and city arguments."""
    return fetch_items(
        timeout=timeout,
        category_ids=category_id,
        city_ids=city_id,
        language=language,
        limit=limit,
        offset=offset,
        sort_type=sort_type,
        params=params,
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", help="write raw JSON to this file instead of standard output"
    )
    parser.add_argument(
        "--category-id",
        action="append",
        dest="category_ids",
        help="filter by category ID (repeat to select multiple categories)",
    )
    parser.add_argument(
        "--city-id",
        action="append",
        dest="city_ids",
        help="filter by city ID (repeat to select multiple cities)",
    )
    parser.add_argument("--language", help="response language")
    parser.add_argument("--limit", type=int, help="maximum number of items")
    parser.add_argument("--offset", type=int, help="number of items to skip")
    parser.add_argument("--sort-type", help="API sort type")
    parser.add_argument(
        "--param",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="add or override an API query parameter (repeatable)",
    )
    args = parser.parse_args(argv)

    extra_params = {}
    for parameter in args.param:
        if "=" not in parameter:
            parser.error("--param must be in KEY=VALUE form")
        key, value = parameter.split("=", 1)
        if not key:
            parser.error("--param key must not be empty")
        extra_params.setdefault(key, []).append(value)

    try:
        data = fetch_items(
            category_ids=args.category_ids,
            city_ids=args.city_ids,
            language=args.language,
            limit=args.limit,
            offset=args.offset,
            sort_type=args.sort_type,
            params=extra_params,
        )
        output = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
        if args.output:
            Path(args.output).write_text(output, encoding="utf-8")
        else:
            sys.stdout.write(output)
    except (APIError, OSError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())