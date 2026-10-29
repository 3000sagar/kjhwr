"""Decision-oriented forecast error metrics."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd


def _valid_rows(frame: pd.DataFrame) -> pd.DataFrame:
    valid = frame.dropna(subset=["forecast_mw", "actual_mw", "horizon_h"]).copy()
    # Negative lead times are hindsight and must not affect forecast accuracy.
    valid = valid.loc[valid["horizon_h"] >= 0].copy()
    if not valid.empty and "source_key" not in valid:
        valid["source_key"] = _source_keys(valid)
    return valid


def _hourly_count(frame: pd.DataFrame) -> int:
    if frame.empty:
        return 0
    if "forecast_source_start_time" in frame:
        source_time = pd.to_datetime(frame["forecast_source_start_time"], utc=True)
    else:
        source_time = pd.to_datetime(frame["start_time"], utc=True).dt.floor("h")
    publish_time = pd.to_datetime(frame["publish_time"], utc=True)
    return int(pd.DataFrame({"source": source_time, "publish": publish_time}).drop_duplicates().shape[0])


def _source_keys(frame: pd.DataFrame) -> pd.Series:
    source = (
        pd.to_datetime(frame["forecast_source_start_time"], utc=True)
        if "forecast_source_start_time" in frame
        else pd.to_datetime(frame["start_time"], utc=True).dt.floor("h")
    )
    publish = pd.to_datetime(frame["publish_time"], utc=True)
    return source.astype(str) + "|" + publish.astype(str)


def build_accuracy_frame(forecasts: pd.DataFrame, actuals: pd.DataFrame) -> pd.DataFrame:
    """Join all aligned forecasts to actuals while retaining hourly source identity."""
    forecast_rows = forecasts.copy()
    actual_rows = actuals[["start_time", "actual_mw"]].copy()
    forecast_rows["start_time"] = pd.to_datetime(forecast_rows["start_time"], utc=True)
    forecast_rows["publish_time"] = pd.to_datetime(forecast_rows["publish_time"], utc=True)
    actual_rows["start_time"] = pd.to_datetime(actual_rows["start_time"], utc=True)
    if "forecast_source_start_time" not in forecast_rows:
        forecast_rows["forecast_source_start_time"] = forecast_rows["start_time"].dt.floor("h")
    else:
        forecast_rows["forecast_source_start_time"] = pd.to_datetime(
            forecast_rows["forecast_source_start_time"], utc=True
        )
    joined = forecast_rows.merge(actual_rows, on="start_time", how="inner", validate="many_to_one")
    joined["horizon_h"] = (
        joined["start_time"] - joined["publish_time"]
    ).dt.total_seconds() / 3600
    joined["error_mw"] = joined["forecast_mw"] - joined["actual_mw"]
    joined["abs_error_mw"] = joined["error_mw"].abs()
    local_times = joined["start_time"].dt.tz_convert("Europe/London")
    joined["delivery_date"] = local_times.dt.date.astype(str)
    joined["source_key"] = _source_keys(joined)
    return joined


def summary(frame: pd.DataFrame) -> dict[str, float | int]:
    valid = _valid_rows(frame)
    expected_points = len(frame)
    with_forecast = int(frame["forecast_mw"].notna().sum()) if "forecast_mw" in frame else 0
    coverage = with_forecast / expected_points if expected_points else float("nan")
    if valid.empty:
        return {
            "mae_mw": float("nan"), "rmse_mw": float("nan"), "bias_mw": float("nan"),
            "spread_mae_mw": float("nan"), "nmae": float("nan"), "buffer_p90_mw": float("nan"),
            "n_hourly_forecasts": 0, "n_half_hour_points": 0,
            "expected_half_hour_points": expected_points,
            "with_forecast_half_hour_points": with_forecast,
            "coverage": coverage,
        }
    errors = valid["forecast_mw"] - valid["actual_mw"]
    mae = float(errors.abs().mean())
    mean_actual = float(valid["actual_mw"].mean())
    return {
        "mae_mw": mae,
        "rmse_mw": float(np.sqrt(np.square(errors).mean())),
        "bias_mw": float(errors.mean()),
        "spread_mae_mw": float((errors - errors.mean()).abs().mean()),
        "nmae": mae / mean_actual if mean_actual else float("nan"),
        "buffer_p90_mw": buffer_p90(valid),
        "n_hourly_forecasts": _hourly_count(valid),
        "n_half_hour_points": len(valid),
        "expected_half_hour_points": expected_points,
        "with_forecast_half_hour_points": with_forecast,
        "coverage": coverage,
    }


def by_hour(frame: pd.DataFrame) -> pd.DataFrame:
    valid = _valid_rows(frame)
    local_time = pd.to_datetime(valid["start_time"], utc=True).dt.tz_convert("Europe/London")
    valid["hour"] = local_time.dt.hour
    valid["error_mw"] = valid["forecast_mw"] - valid["actual_mw"]
    valid["residual_mw"] = -valid["error_mw"]
    return valid.groupby("hour").agg(
        mae_mw=("error_mw", lambda values: values.abs().mean()),
        bias_mw=("error_mw", "mean"),
        spread_mae_mw=("error_mw", lambda values: (values - values.mean()).abs().mean()),
        q10=("residual_mw", lambda values: values.quantile(0.1)),
        q90=("residual_mw", lambda values: values.quantile(0.9)),
        n_hourly_forecasts=("source_key", "nunique"),
    ).reset_index()


def by_day(frame: pd.DataFrame) -> pd.DataFrame:
    valid = _valid_rows(frame)
    valid["error_mw"] = valid["forecast_mw"] - valid["actual_mw"]
    grouped = valid.groupby("delivery_date").agg(
        mae_mw=("error_mw", lambda values: values.abs().mean()),
        bias_mw=("error_mw", "mean"),
        spread_mae_mw=("error_mw", lambda values: (values - values.mean()).abs().mean()),
        n_hourly_forecasts=("source_key", "nunique"),
    ).reset_index()
    return grouped


def by_level(frame: pd.DataFrame) -> pd.DataFrame:
    valid = _valid_rows(frame)
    valid["error_mw"] = valid["forecast_mw"] - valid["actual_mw"]
    # Rank first so repeated actual values do not collapse qcut's tercile edges.
    valid["wind_level"] = pd.qcut(valid["actual_mw"].rank(method="first"), 3, labels=["low", "mid", "high"])
    return valid.groupby("wind_level", observed=False).agg(
        mae_mw=("error_mw", lambda values: values.abs().mean()),
        bias_mw=("error_mw", "mean"),
        n_hourly_forecasts=("source_key", "nunique"),
    ).reset_index()


def by_horizon(frame: pd.DataFrame, bucket_hours: int = 6) -> pd.DataFrame:
    valid = _valid_rows(frame)
    valid["error_mw"] = valid["forecast_mw"] - valid["actual_mw"]
    if valid.empty:
        return pd.DataFrame(columns=["horizon_bucket", "mae_mw", "n_hourly_forecasts"])
    upper = (int(math.floor(valid["horizon_h"].max() / bucket_hours)) + 1) * bucket_hours
    edges = list(range(0, upper + bucket_hours, bucket_hours))
    labels = [f"{low}-{low + bucket_hours}h" for low in edges[:-1]]
    valid["horizon_bucket"] = pd.cut(valid["horizon_h"], bins=edges, labels=labels, right=False)
    valid = valid.dropna(subset=["horizon_bucket"])
    return valid.groupby("horizon_bucket", observed=True).agg(
        mae_mw=("error_mw", lambda values: values.abs().mean()),
        bias_mw=("error_mw", "mean"),
        spread_mae_mw=("error_mw", lambda values: (values - values.mean()).abs().mean()),
        n_hourly_forecasts=("source_key", "nunique"),
    ).reset_index()


def error_histogram(frame: pd.DataFrame, bins: int = 20) -> pd.DataFrame:
    valid = _valid_rows(frame)
    errors = valid["forecast_mw"] - valid["actual_mw"]
    if errors.empty:
        return pd.DataFrame(columns=["bin_low_mw", "bin_high_mw", "count"])
    counts, edges = np.histogram(errors, bins=bins)
    return pd.DataFrame({"bin_low_mw": edges[:-1], "bin_high_mw": edges[1:], "count": counts})


def buffer_p90(frame: pd.DataFrame) -> float:
    valid = _valid_rows(frame)
    if valid.empty:
        return float("nan")
    errors = valid["forecast_mw"] - valid["actual_mw"]
    return float(errors.clip(lower=0).quantile(0.9))


def horizon_comparison(frame: pd.DataFrame) -> pd.DataFrame:
    """Compare hindsight rows with operational lead times for the requested audit."""
    valid = frame.dropna(subset=["forecast_mw", "actual_mw", "horizon_h"]).copy()
    valid["error_mw"] = valid["forecast_mw"] - valid["actual_mw"]
    groups = [("horizon_h < 0", valid["horizon_h"] < 0), ("horizon_h >= 15", valid["horizon_h"] >= 15)]
    rows = []
    for label, mask in groups:
        group = valid.loc[mask]
        rows.append({
            "group": label,
            "mae_mw": float(group["error_mw"].abs().mean()) if not group.empty else float("nan"),
            "correlation": float(group["forecast_mw"].corr(group["actual_mw"])) if len(group) > 1 else float("nan"),
            "n_hourly_forecasts": _hourly_count(group),
            "n_half_hour_points": len(group),
        })
    return pd.DataFrame(rows)
