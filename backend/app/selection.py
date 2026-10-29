"""Select one forecast snapshot for each delivery half-hour."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

LOCAL_ZONE = ZoneInfo("Europe/London")
UTC = timezone.utc
HOURLY_SOURCE = timedelta(hours=1)


def _as_time(value: time | str) -> time:
    return time.fromisoformat(value) if isinstance(value, str) else value


def _as_date(value: date | str) -> date:
    return date.fromisoformat(value) if isinstance(value, str) else value


def _cutoff_utc(delivery_day: date, cutoff_time: time | str) -> pd.Timestamp:
    """Use local civil time so the rule remains correct across GMT/BST changes."""
    local_cutoff = datetime.combine(delivery_day - timedelta(days=1), _as_time(cutoff_time), LOCAL_ZONE)
    return pd.Timestamp(local_cutoff.astimezone(UTC))


def _clean_forecasts(forecasts: pd.DataFrame) -> pd.DataFrame:
    required = {"start_time", "publish_time", "forecast_mw"}
    missing = required - set(forecasts.columns)
    if missing:
        raise ValueError(f"Forecast data is missing columns: {sorted(missing)}")

    clean = forecasts.copy()
    clean["start_time"] = pd.to_datetime(clean["start_time"], utc=True)
    clean["publish_time"] = pd.to_datetime(clean["publish_time"], utc=True)
    clean["forecast_mw"] = pd.to_numeric(clean["forecast_mw"], errors="raise")

    conflicts = clean.groupby(["start_time", "publish_time"], dropna=False)["forecast_mw"].nunique(dropna=False)
    if (conflicts > 1).any():
        raise ValueError("Conflicting forecast values share a start_time and publish_time")
    return clean.drop_duplicates(["start_time", "publish_time", "forecast_mw"])


def _delivery_grid(start: date, end: date) -> pd.DataFrame:
    grid_rows: list[dict[str, Any]] = []
    for day in pd.date_range(start, end, freq="D"):
        delivery_day = day.date()
        local_start = pd.Timestamp(datetime.combine(delivery_day, time.min, LOCAL_ZONE))
        local_end = pd.Timestamp(datetime.combine(delivery_day + timedelta(days=1), time.min, LOCAL_ZONE))
        periods = pd.date_range(local_start, local_end, freq="30min", inclusive="left")
        for local_period in periods:
            utc_period = local_period.tz_convert("UTC")
            grid_rows.append({
                "delivery_date": delivery_day.isoformat(),
                "start_time": utc_period,
            })
    return pd.DataFrame(grid_rows)


def build_decision_table(
    forecasts: pd.DataFrame,
    actuals: pd.DataFrame,
    cutoff_time: time | str = time(9),
    start: date | str = date(2026, 1, 2),
    end: date | str = date(2026, 2, 1),
) -> pd.DataFrame:
    """Pick the latest publication at or before each delivery day's cutoff."""
    first_day, last_day = _as_date(start), _as_date(end)
    if first_day > last_day:
        raise ValueError("start must be on or before end")

    clean_forecasts = _clean_forecasts(forecasts)
    forecast_groups = {
        start_time: group.sort_values("publish_time").to_dict("records")
        for start_time, group in clean_forecasts.groupby("start_time", sort=False)
    }

    actual_rows = actuals.copy()
    if "start_time" not in actual_rows or "actual_mw" not in actual_rows:
        raise ValueError("Actual data must include start_time and actual_mw")
    actual_rows["start_time"] = pd.to_datetime(actual_rows["start_time"], utc=True)
    actual_lookup = actual_rows.drop_duplicates("start_time").set_index("start_time")["actual_mw"]

    grid = _delivery_grid(first_day, last_day)
    rows: list[dict[str, Any]] = []
    for target in grid.itertuples(index=False):
        target_time = target.start_time
        cutoff = _cutoff_utc(date.fromisoformat(target.delivery_date), cutoff_time)
        candidates = [row for row in forecast_groups.get(target_time, []) if row["publish_time"] <= cutoff]
        selected = candidates[-1] if candidates else None

        forecast_mw = selected["forecast_mw"] if selected is not None else float("nan")
        publish_time = selected["publish_time"] if selected is not None else pd.NaT
        horizon_h = (
            (target_time - publish_time).total_seconds() / 3600
            if selected is not None
            else float("nan")
        )
        # A post-delivery publication is not eligible evidence for this decision.
        if selected is not None and horizon_h < 0:
            forecast_mw, publish_time, horizon_h = float("nan"), pd.NaT, float("nan")

        source_time = target_time.floor("h") if pd.notna(publish_time) else pd.NaT
        actual_mw = actual_lookup.get(target_time, float("nan"))
        error_mw = forecast_mw - actual_mw if pd.notna(forecast_mw) and pd.notna(actual_mw) else float("nan")
        rows.append({
            "delivery_date": target.delivery_date,
            "start_time": target_time,
            "forecast_mw": forecast_mw,
            "publish_time": publish_time,
            "forecast_source_start_time": source_time,
            "horizon_h": horizon_h,
            "actual_mw": actual_mw,
            "error_mw": error_mw,
        })

    table = pd.DataFrame(rows)
    if table["start_time"].duplicated().any():
        raise ValueError("Decision table contains duplicate delivery start times")
    return table
