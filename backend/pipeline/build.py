"""Normalize raw Elexon records into compact CSV files."""

from __future__ import annotations

import csv
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from backend.app.selection import build_decision_table

RAW_DIR = Path("data/raw")
PROCESSED_DIR = Path("data/processed")


def parse_utc(value: str) -> datetime:
    """Normalize source timestamps before sorting and joining across datasets."""
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"Timestamp is missing a timezone: {value}")
    return parsed.astimezone(timezone.utc)


def load_json(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list) or any(not isinstance(row, dict) for row in payload):
        raise ValueError(f"Unexpected raw data in {path}: expected a JSON array of objects")
    return payload


def deduplicate(rows: list[dict[str, Any]], key_fields: tuple[str, ...], value_field: str) -> list[dict[str, Any]]:
    """Drop identical repeats but fail on conflicting values for one source key."""
    unique: dict[tuple[str, ...], dict[str, Any]] = {}
    for row in rows:
        key = tuple(str(row[field]) for field in key_fields)
        previous = unique.get(key)
        if previous is not None and previous[value_field] != row[value_field]:
            raise ValueError(f"Conflicting duplicate for {key}: {previous[value_field]} vs {row[value_field]}")
        unique[key] = row
    return list(unique.values())


def write_csv(path: Path, fields: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def build_actuals(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = deduplicate(rows, ("startTime", "fuelType"), "generation")
    if any(row.get("fuelType") != "WIND" for row in rows):
        raise ValueError("FUELHH response included a fuel type other than WIND")
    output = [
        {
            "start_time": parse_utc(row["startTime"]).isoformat().replace("+00:00", "Z"),
            "settlement_date": row["settlementDate"],
            "settlement_period": int(row["settlementPeriod"]),
            "actual_mw": float(row["generation"]),
        }
        for row in rows
    ]
    return sorted(output, key=lambda row: row["start_time"])


def build_forecasts(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], str]:
    rows = deduplicate(rows, ("startTime", "publishTime"), "generation")
    starts = sorted({parse_utc(row["startTime"]) for row in rows})
    gaps = [right - left for left, right in zip(starts, starts[1:])]
    if not gaps:
        raise ValueError("WINDFOR response did not contain enough distinct startTime values to profile resolution")

    min_gap = min(gaps)
    if min_gap == timedelta(hours=1):
        resolution = "hourly"
    elif min_gap == timedelta(minutes=30):
        resolution = "half-hourly"
    else:
        raise ValueError(f"Unexpected WINDFOR resolution: minimum startTime gap is {min_gap}")

    output: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        start = parse_utc(row["startTime"])
        publish = parse_utc(row["publishTime"])
        targets = [start]
        if resolution == "hourly":
            targets.append(start + timedelta(minutes=30))
        for target in targets:
            key = (target.isoformat().replace("+00:00", "Z"), publish.isoformat().replace("+00:00", "Z"))
            output[key] = {
                "start_time": key[0],
                "publish_time": key[1],
                "forecast_mw": float(row["generation"]),
            }

    aligned = list(output.values())
    aligned.sort(key=lambda row: (row["start_time"], row["publish_time"]))
    return aligned, resolution


def main() -> None:
    actuals = build_actuals(load_json(RAW_DIR / "fuelhh.json"))
    forecasts, resolution = build_forecasts(load_json(RAW_DIR / "windfor.json"))
    write_csv(PROCESSED_DIR / "actuals.csv", list(actuals[0]), actuals)
    write_csv(PROCESSED_DIR / "forecasts.csv", list(forecasts[0]), forecasts)
    decisions = build_decision_table(pd.DataFrame(forecasts), pd.DataFrame(actuals))
    decisions.to_csv(PROCESSED_DIR / "decision_table.csv", index=False)
    from backend.pipeline.build_cache import build_cache

    outcome_count = build_cache()
    print(f"WINDFOR native resolution: {resolution}")
    print(f"Aligned forecast rows: {len(forecasts)}")
    print(f"Decision table rows: {len(decisions)}")
    print(f"Endpoint cache: {outcome_count} selection outcomes x 2 modes")


if __name__ == "__main__":
    main()
