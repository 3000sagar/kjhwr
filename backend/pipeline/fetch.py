"""Download the source datasets for the January 2026 analysis."""

from __future__ import annotations

import json
import os
import time
from datetime import date, datetime, time as datetime_time, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

API_BASE = os.environ.get("BMRS_API_BASE", "").rstrip("/")
RAW_DIR = Path("data/raw")
# The extra lookback supplies trailing-error history for the first delivery days.
ACTUAL_START = date(2025, 12, 18)
ACTUAL_END = date(2026, 2, 1)
FORECAST_PUBLISH_START = date(2025, 12, 18)
FORECAST_PUBLISH_END = date(2026, 2, 1)
MAX_ATTEMPTS = 5


def request_json(dataset: str, params: dict[str, str]) -> list[dict[str, Any]]:
    """Fetch one small window; bounded retries handle temporary service limits."""
    if not API_BASE:
        raise RuntimeError("Set BMRS_API_BASE to the dataset API base URL before fetching")
    url = f"{API_BASE}/datasets/{dataset}/stream?{urlencode(params)}"
    request = Request(url, headers={"Accept": "application/json"})

    for attempt in range(MAX_ATTEMPTS):
        try:
            with urlopen(request, timeout=60) as response:
                payload = json.load(response)
            if not isinstance(payload, list) or any(not isinstance(row, dict) for row in payload):
                raise ValueError(f"Unexpected {dataset} response: expected a JSON array of objects")
            return payload
        except HTTPError as exc:
            if exc.code not in {429, 500, 502, 503, 504} or attempt == MAX_ATTEMPTS - 1:
                raise RuntimeError(f"{dataset} request failed with HTTP {exc.code}: {url}") from exc
        except (TimeoutError, URLError) as exc:
            if attempt == MAX_ATTEMPTS - 1:
                raise RuntimeError(f"{dataset} request failed: {exc}") from exc
        time.sleep(2**attempt)

    raise RuntimeError(f"{dataset} request exhausted retries")


def day_windows(first: date, last: date) -> list[date]:
    """Return inclusive daily windows so requests stay deliberately small."""
    return [first + timedelta(days=offset) for offset in range((last - first).days + 1)]


def fetch_actuals() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for day in day_windows(ACTUAL_START, ACTUAL_END):
        rows.extend(
            request_json(
                "FUELHH",
                {
                    "settlementDateFrom": day.isoformat(),
                    "settlementDateTo": day.isoformat(),
                    "fuelType": "WIND",
                },
            )
        )
    return rows


def fetch_forecasts() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for day in day_windows(FORECAST_PUBLISH_START, FORECAST_PUBLISH_END):
        start = datetime.combine(day, datetime_time.min, tzinfo=timezone.utc)
        end = start + timedelta(days=1) - timedelta(seconds=1)
        rows.extend(
            request_json(
                "WINDFOR",
                {
                    "publishDateTimeFrom": start.isoformat().replace("+00:00", "Z"),
                    "publishDateTimeTo": end.isoformat().replace("+00:00", "Z"),
                },
            )
        )
    return rows


def save_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows, separators=(",", ":")), encoding="utf-8")


def main() -> None:
    actuals = fetch_actuals()
    save_rows(RAW_DIR / "fuelhh.json", actuals)
    print(f"FUELHH rows fetched: {len(actuals)}")

    forecasts = fetch_forecasts()
    save_rows(RAW_DIR / "windfor.json", forecasts)
    print(f"WINDFOR rows fetched: {len(forecasts)}")


if __name__ == "__main__":
    main()
