"""Read-only API over the processed forecast and actual CSV files."""

from __future__ import annotations

from bisect import bisect_right
from contextlib import asynccontextmanager
from datetime import date, time, timedelta
import json
from typing import Literal

import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from backend.app.config import DEFAULT_CUTOFF, LOCAL_ZONE, PROCESSED_DIR, ROOT_DIR, WINDOW_END, WINDOW_START
from backend.app.data import load_data
from backend.app.metrics import (
    _hourly_count,
    _valid_rows,
    by_day,
    by_horizon,
    by_hour,
    build_accuracy_frame,
    buffer_p90,
    error_histogram,
    summary,
)
from backend.app.schemas import (
    AccuracySummary,
    ConfigResponse,
    DayMetric,
    DayPoint,
    DayResponse,
    DaySummary,
    DeliveryDay,
    HealthResponse,
    HistogramBin,
    HorizonMetric,
    HourMetric,
)
from backend.app.selection import build_decision_table

Mode = Literal["raw", "bias_corrected"]


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    _load_cutoff_cache()
    yield


app = FastAPI(title="Day-Ahead Wind Forecast API", version="1.0.0", lifespan=_lifespan)


@app.exception_handler(404)
async def not_found(request: Request, _error: HTTPException) -> JSONResponse:
    """Include the path so a serverless rewrite mismatch is visible in the response."""
    return JSONResponse(
        status_code=404,
        content={"detail": "Not found", "path": request.scope["path"]},
    )


_OUTCOME_BREAKPOINTS: list[time] = []
_BREAKPOINT_OUTCOME_IDS: list[int] = []
_OUTCOME_TABLES: dict[int, dict[Mode, list[dict[str, object]]]] = {}
_OUTCOME_PAYLOADS: dict[int, dict[Mode, dict[str, object]]] = {}
_OUTCOME_SIGNATURES: dict[tuple[tuple[str, tuple[str, ...]], ...], int] = {}
_HORIZON_PAYLOADS: dict[tuple[int, Mode], list[dict[str, object]]] = {}
_SUMMARY_RANGE_CACHE: dict[tuple[int, Mode, date, date], dict[str, object]] = {}
_DAY_PAYLOADS: dict[tuple[int, Mode, str], dict[str, object]] = {}


def _load_cutoff_cache() -> None:
    """Load generated endpoint payloads only; expensive analysis belongs in the pipeline."""
    if _OUTCOME_BREAKPOINTS:
        return
    cache_dir = PROCESSED_DIR / "cache"
    manifest = json.loads((cache_dir / "manifest.json").read_text(encoding="utf-8"))
    for item in manifest["breakpoints"]:
        _OUTCOME_BREAKPOINTS.append(time.fromisoformat(item["cutoff"]))
        _BREAKPOINT_OUTCOME_IDS.append(int(item["outcome_id"]))
    for outcome_id in manifest["outcome_ids"]:
        _OUTCOME_TABLES[int(outcome_id)] = {}
        _OUTCOME_PAYLOADS[int(outcome_id)] = {}
        for mode in ("raw", "bias_corrected"):
            path = cache_dir / f"outcome-{int(outcome_id):02d}-{mode}.json"
            cached = json.loads(path.read_text(encoding="utf-8"))
            _OUTCOME_TABLES[int(outcome_id)][mode] = cached["decision_rows"]
            _OUTCOME_PAYLOADS[int(outcome_id)][mode] = cached["payload"]
            _HORIZON_PAYLOADS[(int(outcome_id), mode)] = cached["horizon"]
            for delivery_day, day_payload in cached["days"].items():
                _DAY_PAYLOADS[(int(outcome_id), mode, delivery_day)] = day_payload
            response = cached["summary_response"]
            first = date.fromisoformat(response["from_date"])
            last = date.fromisoformat(response["to_date"])
            _SUMMARY_RANGE_CACHE[(int(outcome_id), mode, first, last)] = response


def _selection_signature(table: pd.DataFrame) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """Keep the selected publication for every half-hour, not just each day's first run."""
    groups = []
    for delivery_day, frame in table.groupby("delivery_date", sort=True):
        publishes = tuple("" if pd.isna(value) else value.isoformat() for value in frame["publish_time"])
        groups.append((delivery_day, publishes))
    return tuple(groups)


def _cutoff_events(forecasts: pd.DataFrame, first: date, last: date) -> list[time]:
    targets = forecasts[["start_time", "publish_time"]].copy()
    targets["delivery_date"] = targets["start_time"].dt.tz_convert(LOCAL_ZONE).dt.date
    local_publish = targets["publish_time"].dt.tz_convert(LOCAL_ZONE)
    targets["publish_date"] = local_publish.dt.date
    targets["publish_clock"] = local_publish.dt.time
    target_days = targets["delivery_date"].between(first, last)
    # Only prior-day publications create a new cutoff outcome during that day's clock.
    prior_day = targets["publish_date"] == targets["delivery_date"].map(lambda day: day - timedelta(days=1))
    events = set(targets.loc[target_days & prior_day, "publish_clock"])
    return sorted({time.min, *events})


def _prepare_cutoff_cache() -> None:
    if _OUTCOME_BREAKPOINTS:
        return
    forecasts, actuals = load_data()
    history_start = WINDOW_START - timedelta(days=8)
    events = _cutoff_events(forecasts, history_start, WINDOW_END)
    last_signature = None
    for cutoff in events:
        raw = build_decision_table(
            forecasts,
            actuals,
            cutoff_time=cutoff,
            start=history_start,
            end=WINDOW_END,
        )
        signature = _selection_signature(raw)
        outcome_id = _OUTCOME_SIGNATURES.get(signature)
        if outcome_id is None:
            outcome_id = len(_OUTCOME_SIGNATURES)
            _OUTCOME_SIGNATURES[signature] = outcome_id
            corrections = _trailing_bias_by_day(raw, WINDOW_START, WINDOW_END)
            corrected = raw.loc[
                raw["delivery_date"].between(WINDOW_START.isoformat(), WINDOW_END.isoformat())
            ].copy()
            corrected["correction_bias_mw"] = corrected["delivery_date"].map(corrections)
            corrected["forecast_mw"] -= corrected["correction_bias_mw"]
            corrected["error_mw"] = corrected["forecast_mw"] - corrected["actual_mw"]
            _OUTCOME_TABLES[outcome_id] = {"raw": raw, "bias_corrected": corrected}
        if outcome_id != last_signature:
            _OUTCOME_BREAKPOINTS.append(cutoff)
            _BREAKPOINT_OUTCOME_IDS.append(outcome_id)
            last_signature = outcome_id

    # Warm both modes for every distinct selection so the first request is also fast.
    for outcome_id in range(len(_OUTCOME_TABLES)):
        for mode in ("raw", "bias_corrected"):
            _warm_outcome(outcome_id, mode)


def _outcome_id(cutoff: time) -> int:
    _load_cutoff_cache()
    index = bisect_right(_OUTCOME_BREAKPOINTS, cutoff) - 1
    return _BREAKPOINT_OUTCOME_IDS[max(0, index)]


def _warm_outcome(outcome_id: int, mode: Mode) -> None:
    table = _OUTCOME_TABLES[outcome_id][mode]
    scored = table.loc[
        table["delivery_date"].between(WINDOW_START.isoformat(), WINDOW_END.isoformat())
    ].copy()
    metrics = summary(scored)
    low, high = _bootstrap_buffer_ci(scored)
    raw = _OUTCOME_TABLES[outcome_id]["raw"]
    corrected = _OUTCOME_TABLES[outcome_id]["bias_corrected"]
    raw_scored = raw.loc[raw["delivery_date"].between(WINDOW_START.isoformat(), WINDOW_END.isoformat())]
    paired = _OUTCOME_PAYLOADS.get(outcome_id, {}).get("raw", {}).get("paired")
    if paired is None:
        paired = _paired_summary_deltas(raw_scored, corrected)
    days = []
    for delivery_day, group in scored.groupby("delivery_date", sort=True):
        days.append({
            "delivery_date": delivery_day,
            "expected": len(group),
            "with_forecast": int(group["forecast_mw"].notna().sum()),
        })
    _OUTCOME_PAYLOADS.setdefault(outcome_id, {})[mode] = {
        "summary": metrics,
        "buffer_ci": (low, high),
        "paired": paired,
        "delivery_days": days,
        "by_hour": by_hour(scored).to_dict(orient="records"),
        "by_day": by_day(scored).to_dict(orient="records"),
        "histogram": error_histogram(scored).to_dict(orient="records"),
    }
    _SUMMARY_RANGE_CACHE[(outcome_id, mode, WINDOW_START, WINDOW_END)] = {
        "from_date": WINDOW_START,
        "to_date": WINDOW_END,
        "mode": mode,
        "mae_mw": metrics["mae_mw"],
        "rmse_mw": metrics["rmse_mw"],
        "bias_mw": metrics["bias_mw"],
        "spread_mae_mw": metrics["spread_mae_mw"],
        "nmae": metrics["nmae"],
        "buffer_p90_mw": metrics["buffer_p90_mw"],
        "buffer_p90_ci_low_mw": low,
        "buffer_p90_ci_high_mw": high,
        **paired,
        "ci_level": 0.9,
        "ci_method": "delivery-day bootstrap percentile interval, 1000 draws",
        "n_hourly_forecasts": metrics["n_hourly_forecasts"],
        "n_half_hour_points": metrics["n_half_hour_points"],
        "coverage": metrics["coverage"],
    }
    horizon = _accuracy_forecasts_for_outcome(outcome_id, mode)
    _HORIZON_PAYLOADS[(outcome_id, mode)] = by_horizon(horizon).to_dict(orient="records")


def _accuracy_forecasts_for_outcome(outcome_id: int, mode: Mode) -> pd.DataFrame:
    forecasts, actuals = load_data()
    joined = build_accuracy_frame(forecasts, actuals)
    joined = joined.loc[
        joined["delivery_date"].between(WINDOW_START.isoformat(), WINDOW_END.isoformat())
    ].copy()
    if mode == "bias_corrected":
        decisions = pd.DataFrame(_OUTCOME_TABLES[outcome_id][mode])
        daily_bias = decisions.groupby("delivery_date")["correction_bias_mw"].first().to_dict()
        joined["correction_bias_mw"] = joined["delivery_date"].map(daily_bias)
        joined["forecast_mw"] -= joined["correction_bias_mw"]
        joined["error_mw"] = joined["forecast_mw"] - joined["actual_mw"]
        joined["abs_error_mw"] = joined["error_mw"].abs()
    return joined


def _summary_response(outcome_id: int, mode: Mode, first: date, last: date) -> dict[str, object]:
    key = (outcome_id, mode, first, last)
    if key not in _SUMMARY_RANGE_CACHE:
        table = pd.DataFrame(_OUTCOME_TABLES[outcome_id][mode])
        for column in ("start_time", "publish_time", "forecast_source_start_time"):
            if column in table:
                table[column] = pd.to_datetime(table[column], utc=True)
        table = table.loc[table["delivery_date"].between(first.isoformat(), last.isoformat())].copy()
        metrics = summary(table)
        low, high = _bootstrap_buffer_ci(table)
        raw = pd.DataFrame(_OUTCOME_TABLES[outcome_id]["raw"])
        raw["start_time"] = pd.to_datetime(raw["start_time"], utc=True)
        raw["publish_time"] = pd.to_datetime(raw["publish_time"], utc=True)
        raw = raw.loc[raw["delivery_date"].between(first.isoformat(), last.isoformat())].copy()
        corrected = pd.DataFrame(_OUTCOME_TABLES[outcome_id]["bias_corrected"])
        corrected["start_time"] = pd.to_datetime(corrected["start_time"], utc=True)
        corrected["publish_time"] = pd.to_datetime(corrected["publish_time"], utc=True)
        corrected = corrected.loc[corrected["delivery_date"].between(first.isoformat(), last.isoformat())].copy()
        paired = _paired_summary_deltas(raw, corrected)
        _SUMMARY_RANGE_CACHE[key] = {
            "from_date": first,
            "to_date": last,
            "mode": mode,
            "mae_mw": metrics["mae_mw"],
            "rmse_mw": metrics["rmse_mw"],
            "bias_mw": metrics["bias_mw"],
            "spread_mae_mw": metrics["spread_mae_mw"],
            "nmae": metrics["nmae"],
            "buffer_p90_mw": metrics["buffer_p90_mw"],
            "buffer_p90_ci_low_mw": low,
            "buffer_p90_ci_high_mw": high,
            **paired,
            "ci_level": 0.9,
            "ci_method": "delivery-day bootstrap percentile interval, 1000 draws",
            "n_hourly_forecasts": metrics["n_hourly_forecasts"],
            "n_half_hour_points": metrics["n_half_hour_points"],
            "coverage": metrics["coverage"],
        }
    return dict(_SUMMARY_RANGE_CACHE[key])


def _cutoff_label(cutoff: time) -> str:
    return cutoff.strftime("%H:%M")


def _validate_window(first: date, last: date) -> None:
    if first > last:
        raise HTTPException(status_code=422, detail="from must be on or before to")
    if first < WINDOW_START or last > WINDOW_END:
        raise HTTPException(status_code=422, detail="Date range is outside the analysis window")


def _decisions(first: date, last: date, cutoff: time, mode: Mode) -> pd.DataFrame:
    outcome_id = _outcome_id(cutoff)
    selected = pd.DataFrame(_OUTCOME_TABLES[outcome_id][mode])
    for column in ("start_time", "publish_time", "forecast_source_start_time"):
        if column in selected:
            selected[column] = pd.to_datetime(selected[column], utc=True)
    return selected.loc[selected["delivery_date"].between(first.isoformat(), last.isoformat())].copy()


def _trailing_bias_by_day(
    history: pd.DataFrame,
    first: date,
    last: date,
) -> dict[str, float]:
    # A fixed D-8..D-2 window uses only errors available before delivery-day D-1.
    valid = history.dropna(subset=["forecast_mw", "actual_mw"]).copy()
    valid["error_mw"] = valid["forecast_mw"] - valid["actual_mw"]
    daily = valid.groupby("delivery_date")["error_mw"].mean().to_dict()
    corrections: dict[str, float] = {}
    for day in pd.date_range(first, last, freq="D"):
        delivery_day = day.date()
        prior_days = [
            (delivery_day - timedelta(days=offset)).isoformat()
            for offset in range(8, 1, -1)
        ]
        if not all(prior in daily for prior in prior_days):
            raise HTTPException(
                status_code=422,
                detail=f"Seven complete trailing-error days are unavailable for {delivery_day}",
            )
        corrections[delivery_day.isoformat()] = float(np.mean([daily[key] for key in prior_days]))
    return corrections


def _accuracy_forecasts(cutoff: time, mode: Mode) -> pd.DataFrame:
    return _accuracy_forecasts_for_outcome(_outcome_id(cutoff), mode)


def _bootstrap_buffer_ci(frame: pd.DataFrame, draws: int = 1000) -> tuple[float | None, float | None]:
    valid = _valid_rows(frame)
    if valid.empty:
        return None, None
    valid["error_mw"] = valid["forecast_mw"] - valid["actual_mw"]
    groups = [group["error_mw"].to_numpy(dtype=float) for _, group in valid.groupby("delivery_date")]
    if not groups:
        return None, None
    rng = np.random.default_rng(20261029)
    day_count = len(groups)
    estimates = np.empty(draws, dtype=float)
    for draw in range(draws):
        sampled_days = rng.integers(0, day_count, size=day_count)
        sampled_errors = np.concatenate([groups[index] for index in sampled_days])
        estimates[draw] = np.quantile(np.maximum(sampled_errors, 0), 0.9)
    return float(np.quantile(estimates, 0.05)), float(np.quantile(estimates, 0.95))


def _paired_summary_deltas(
    raw: pd.DataFrame,
    corrected: pd.DataFrame,
    draws: int = 1000,
) -> dict[str, float]:
    raw_rows = raw[["delivery_date", "start_time", "forecast_mw", "actual_mw"]]
    corrected_rows = corrected[["delivery_date", "start_time", "forecast_mw", "actual_mw"]]
    paired = raw_rows.merge(
        corrected_rows,
        on=["delivery_date", "start_time", "actual_mw"],
        suffixes=("_raw", "_corrected"),
        validate="one_to_one",
    ).dropna(subset=["forecast_mw_raw", "forecast_mw_corrected", "actual_mw"])
    paired["error_raw"] = paired["forecast_mw_raw"] - paired["actual_mw"]
    paired["error_corrected"] = paired["forecast_mw_corrected"] - paired["actual_mw"]
    raw_mae = float(paired["error_raw"].abs().mean())
    corrected_mae = float(paired["error_corrected"].abs().mean())
    raw_buffer = float(paired["error_raw"].clip(lower=0).quantile(0.9))
    corrected_buffer = float(paired["error_corrected"].clip(lower=0).quantile(0.9))

    groups = [
        (group["error_raw"].to_numpy(dtype=float), group["error_corrected"].to_numpy(dtype=float))
        for _, group in paired.groupby("delivery_date", sort=True)
    ]
    rng = np.random.default_rng(20261029)
    mae_deltas = np.empty(draws, dtype=float)
    buffer_deltas = np.empty(draws, dtype=float)
    for draw in range(draws):
        sampled = rng.integers(0, len(groups), size=len(groups))
        errors_raw = np.concatenate([groups[index][0] for index in sampled])
        errors_corrected = np.concatenate([groups[index][1] for index in sampled])
        mae_deltas[draw] = np.abs(errors_raw).mean() - np.abs(errors_corrected).mean()
        buffer_deltas[draw] = (
            np.quantile(np.maximum(errors_raw, 0), 0.9)
            - np.quantile(np.maximum(errors_corrected, 0), 0.9)
        )
    return {
        "raw_minus_corrected_mae_mw": raw_mae - corrected_mae,
        "raw_minus_corrected_mae_ci_low_mw": float(np.quantile(mae_deltas, 0.05)),
        "raw_minus_corrected_mae_ci_high_mw": float(np.quantile(mae_deltas, 0.95)),
        "raw_minus_corrected_buffer_p90_mw": raw_buffer - corrected_buffer,
        "raw_minus_corrected_buffer_p90_ci_low_mw": float(np.quantile(buffer_deltas, 0.05)),
        "raw_minus_corrected_buffer_p90_ci_high_mw": float(np.quantile(buffer_deltas, 0.95)),
    }


def _require_day(day: date) -> None:
    if day < WINDOW_START or day > WINDOW_END:
        raise HTTPException(status_code=404, detail="Delivery day is outside the analysis window")


@app.get("/api/health", response_model=HealthResponse)
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/config", response_model=ConfigResponse)
def config(cutoff: time = DEFAULT_CUTOFF) -> dict[str, object]:
    return {
        "cutoff": _cutoff_label(cutoff),
        "timezone": "Europe/London",
        "window_start": WINDOW_START,
        "window_end": WINDOW_END,
        "assumptions": [
            "A decision for delivery day D uses the D-1 cutoff in Europe/London.",
            "The cutoff is configurable and precedes the EPEX 09:20 and N2EX 09:50 hourly auction closes.",
            "Selection uses the latest WINDFOR publishTime at or before the cutoff.",
            "Hourly WINDFOR values are repeated across two half-hour delivery periods.",
            "Spread is mean absolute error after removing the mean error bias.",
            "Bias-corrected mode subtracts mean decision error from D-8 through D-2.",
            "P90 buffer is the 90th percentile of positive forecast error.",
        ],
    }


@app.get("/api/delivery-days", response_model=list[DeliveryDay])
def delivery_days(
    cutoff: time = DEFAULT_CUTOFF,
    mode: Mode = "raw",
) -> list[dict[str, object]]:
    outcome_id = _outcome_id(cutoff)
    return [dict(item) for item in _OUTCOME_PAYLOADS[outcome_id][mode]["delivery_days"]]


@app.get("/api/day/{delivery_day}", response_model=DayResponse)
def day_view(
    delivery_day: date,
    cutoff: time = DEFAULT_CUTOFF,
    mode: Mode = "raw",
) -> dict[str, object]:
    _require_day(delivery_day)
    outcome_id = _outcome_id(cutoff)
    cached = _DAY_PAYLOADS.get((outcome_id, mode, delivery_day.isoformat()))
    if cached is not None:
        return {**cached, "cutoff": _cutoff_label(cutoff), "mode": mode}
    table = _decisions(delivery_day, delivery_day, cutoff, mode)
    all_days = _decisions(WINDOW_START, WINDOW_END, cutoff, mode)
    all_days = all_days.dropna(subset=["forecast_mw", "actual_mw"]).copy()
    all_days["residual_mw"] = all_days["actual_mw"] - all_days["forecast_mw"]
    all_days["hour"] = all_days["start_time"].dt.tz_convert(LOCAL_ZONE).dt.hour
    bands = all_days.groupby("hour")["residual_mw"].quantile([0.1, 0.9]).unstack()
    bands.columns = ["q10", "q90"]

    points = []
    for row in table.itertuples(index=False):
        local_hour = row.start_time.tz_convert(LOCAL_ZONE).hour
        forecast = None if pd.isna(row.forecast_mw) else float(row.forecast_mw)
        low = high = None
        if forecast is not None and local_hour in bands.index:
            low = forecast + float(bands.loc[local_hour, "q10"])
            high = forecast + float(bands.loc[local_hour, "q90"])
        points.append({
            "start_time": row.start_time,
            "forecast_mw": forecast,
            "publish_time": None if pd.isna(row.publish_time) else row.publish_time,
            "horizon_h": None if pd.isna(row.horizon_h) else float(row.horizon_h),
            "actual_mw": None if pd.isna(row.actual_mw) else float(row.actual_mw),
            "error_mw": None if pd.isna(row.error_mw) else float(row.error_mw),
            "band_low_mw": low,
            "band_high_mw": high,
        })

    valid = table.dropna(subset=["forecast_mw", "actual_mw"])
    errors = valid["forecast_mw"] - valid["actual_mw"]
    bias = float(errors.mean()) if len(errors) else None
    return {
        "delivery_date": delivery_day,
        "cutoff": _cutoff_label(cutoff),
        "mode": mode,
        "points": points,
        "summary": {
            "forecast_mwh": float(valid["forecast_mw"].sum() * 0.5),
            "actual_mwh": float(table["actual_mw"].sum() * 0.5),
            "peak_forecast_mw": float(valid["forecast_mw"].max()) if len(valid) else None,
            "min_forecast_mw": float(valid["forecast_mw"].min()) if len(valid) else None,
            "mae_mw": float(errors.abs().mean()) if len(errors) else None,
            "bias_mw": bias,
            "spread_mae_mw": float((errors - bias).abs().mean()) if len(errors) else None,
            "coverage": len(valid) / len(table) if len(table) else 0.0,
        },
    }


@app.get("/api/accuracy/summary", response_model=AccuracySummary)
def accuracy_summary(
    from_date: date = Query(WINDOW_START, alias="from"),
    to_date: date = Query(WINDOW_END, alias="to"),
    cutoff: time = DEFAULT_CUTOFF,
    mode: Mode = "raw",
) -> dict[str, object]:
    _validate_window(from_date, to_date)
    outcome_id = _outcome_id(cutoff)
    response = _summary_response(outcome_id, mode, from_date, to_date)
    response["cutoff"] = _cutoff_label(cutoff)
    return response


@app.get("/api/accuracy/by-hour", response_model=list[HourMetric])
def accuracy_by_hour(cutoff: time = DEFAULT_CUTOFF, mode: Mode = "raw") -> list[dict[str, object]]:
    outcome_id = _outcome_id(cutoff)
    return [dict(row) for row in _OUTCOME_PAYLOADS[outcome_id][mode]["by_hour"]]


@app.get("/api/accuracy/by-day", response_model=list[DayMetric])
def accuracy_by_day(cutoff: time = DEFAULT_CUTOFF, mode: Mode = "raw") -> list[dict[str, object]]:
    outcome_id = _outcome_id(cutoff)
    return [dict(row) for row in _OUTCOME_PAYLOADS[outcome_id][mode]["by_day"]]


@app.get("/api/accuracy/by-horizon", response_model=list[HorizonMetric])
def accuracy_by_horizon(cutoff: time = DEFAULT_CUTOFF, mode: Mode = "raw") -> list[dict[str, object]]:
    outcome_id = _outcome_id(cutoff)
    return [dict(row) for row in _HORIZON_PAYLOADS[(outcome_id, mode)]]


@app.get("/api/accuracy/histogram", response_model=list[HistogramBin])
def accuracy_histogram(cutoff: time = DEFAULT_CUTOFF, mode: Mode = "raw") -> list[dict[str, object]]:
    outcome_id = _outcome_id(cutoff)
    return [dict(row) for row in _OUTCOME_PAYLOADS[outcome_id][mode]["histogram"]]


_FRONTEND_DIST = ROOT_DIR / "frontend" / "dist"
if _FRONTEND_DIST.is_dir():
    _ASSET_DIR = _FRONTEND_DIST / "assets"
    if _ASSET_DIR.is_dir():
        app.mount("/assets", StaticFiles(directory=_ASSET_DIR), name="assets")

    @app.get("/", include_in_schema=False)
    def frontend_index() -> FileResponse:
        return FileResponse(_FRONTEND_DIST / "index.html")

    @app.get("/{asset_path:path}", include_in_schema=False)
    def frontend_route(asset_path: str) -> FileResponse:
        if asset_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not found")
        candidate = (_FRONTEND_DIST / asset_path).resolve()
        if _FRONTEND_DIST.resolve() not in candidate.parents:
            raise HTTPException(status_code=404, detail="Not found")
        # Client-side routes need the app shell so React can resolve the deep link.
        return FileResponse(candidate if candidate.is_file() else _FRONTEND_DIST / "index.html")
