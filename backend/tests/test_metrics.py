import pandas as pd
import pytest

from backend.app.metrics import by_horizon, build_accuracy_frame, horizon_comparison, summary


def test_overforecast_sign_and_p90_buffer_on_known_example() -> None:
    frame = pd.DataFrame({
        "start_time": pd.date_range("2026-01-02T00:00:00Z", periods=10, freq="30min"),
        "forecast_source_start_time": pd.date_range("2026-01-02T00:00:00Z", periods=10, freq="h"),
        "publish_time": [pd.Timestamp("2026-01-01T08:00:00Z")] * 10,
        "forecast_mw": [110.0] + [100.0] * 9,
        "actual_mw": [100.0] * 10,
        "horizon_h": [16.0] * 10,
    })
    result = summary(frame)
    assert result["bias_mw"] == 1.0
    assert result["buffer_p90_mw"] == pytest.approx(1.0)


def test_decision_sample_size_counts_hourly_forecasts_not_aligned_rows() -> None:
    frame = pd.DataFrame({
        "start_time": pd.to_datetime(["2026-01-02T10:00:00Z", "2026-01-02T10:30:00Z"], utc=True),
        "forecast_source_start_time": pd.to_datetime(["2026-01-02T10:00:00Z"] * 2, utc=True),
        "publish_time": pd.to_datetime(["2026-01-01T08:00:00Z"] * 2, utc=True),
        "forecast_mw": [100.0, 100.0],
        "actual_mw": [90.0, 110.0],
        "horizon_h": [26.0, 26.5],
    })
    result = summary(frame)
    assert result["n_hourly_forecasts"] == 1
    assert result["n_half_hour_points"] == 2


def test_summary_reports_bias_separately_from_bias_removed_spread() -> None:
    frame = pd.DataFrame({
        "start_time": pd.to_datetime(["2026-01-02T00:00:00Z", "2026-01-02T00:30:00Z"], utc=True),
        "forecast_source_start_time": pd.to_datetime(["2026-01-02T00:00:00Z"] * 2, utc=True),
        "publish_time": pd.to_datetime(["2026-01-01T08:00:00Z"] * 2, utc=True),
        "forecast_mw": [108.0, 112.0],
        "actual_mw": [100.0, 100.0],
        "horizon_h": [16.0, 16.5],
    })

    result = summary(frame)

    assert result["bias_mw"] == 10.0
    assert result["mae_mw"] == 10.0
    assert result["spread_mae_mw"] == 2.0


def test_horizon_analysis_excludes_negative_horizons() -> None:
    frame = pd.DataFrame({
        "start_time": pd.to_datetime(["2026-01-02T00:00:00Z", "2026-01-02T00:30:00Z"], utc=True),
        "forecast_source_start_time": pd.to_datetime(["2026-01-02T00:00:00Z"] * 2, utc=True),
        "publish_time": pd.to_datetime(["2026-01-02T01:00:00Z", "2026-01-01T08:00:00Z"], utc=True),
        "forecast_mw": [999.0, 110.0],
        "actual_mw": [100.0, 100.0],
        "horizon_h": [-1.0, 16.5],
        "error_mw": [899.0, 10.0],
        "source_key": ["negative", "positive"],
    })
    buckets = by_horizon(frame)
    assert len(buckets) == 1
    assert buckets.iloc[0]["horizon_bucket"] == "12-18h"
    assert buckets.iloc[0]["mae_mw"] == 10.0
    assert buckets.iloc[0]["n_hourly_forecasts"] == 1


def test_horizon_comparison_reports_negative_and_operational_rows() -> None:
    forecasts = pd.DataFrame({
        "start_time": ["2026-01-02T00:00:00Z", "2026-01-02T00:30:00Z", "2026-01-02T01:00:00Z"],
        "publish_time": ["2026-01-02T01:00:00Z", "2026-01-01T08:00:00Z", "2026-01-01T08:00:00Z"],
        "forecast_mw": [999.0, 110.0, 90.0],
    })
    actuals = pd.DataFrame({
        "start_time": ["2026-01-02T00:00:00Z", "2026-01-02T00:30:00Z", "2026-01-02T01:00:00Z"],
        "actual_mw": [100.0, 100.0, 100.0],
    })
    joined = build_accuracy_frame(forecasts, actuals)
    comparison = horizon_comparison(joined).set_index("group")
    assert comparison.loc["horizon_h < 0", "mae_mw"] == 899.0
    assert comparison.loc["horizon_h >= 15", "mae_mw"] == 10.0
    assert comparison.loc["horizon_h >= 15", "n_hourly_forecasts"] == 2
    horizon_rows = by_horizon(joined)
    assert horizon_rows["mae_mw"].tolist() == [10.0]
