from datetime import date, time
from time import perf_counter

import pandas as pd
import pytest
import backend.app.main as api

from backend.app.main import (
    _DAY_PAYLOADS,
    _HORIZON_PAYLOADS,
    _OUTCOME_BREAKPOINTS,
    _BREAKPOINT_OUTCOME_IDS,
    _OUTCOME_PAYLOADS,
    _OUTCOME_TABLES,
    _SUMMARY_RANGE_CACHE,
    _bootstrap_buffer_ci,
    _load_cutoff_cache,
    _outcome_id,
    _paired_summary_deltas,
    _trailing_bias_by_day,
    accuracy_summary,
    day_view,
)
from backend.app.config import WINDOW_END, WINDOW_START
from backend.app.metrics import by_day, by_hour, by_horizon, error_histogram, summary


def test_startup_cache_loads_in_under_two_seconds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("backend.app.main._OUTCOME_BREAKPOINTS", [])
    monkeypatch.setattr("backend.app.main._BREAKPOINT_OUTCOME_IDS", [])
    monkeypatch.setattr("backend.app.main._OUTCOME_TABLES", {})
    monkeypatch.setattr("backend.app.main._OUTCOME_PAYLOADS", {})
    monkeypatch.setattr("backend.app.main._HORIZON_PAYLOADS", {})
    monkeypatch.setattr("backend.app.main._SUMMARY_RANGE_CACHE", {})
    monkeypatch.setattr("backend.app.main._DAY_PAYLOADS", {})

    started = perf_counter()
    _load_cutoff_cache()
    elapsed = perf_counter() - started

    assert elapsed < 2.0
    assert len(api._OUTCOME_TABLES) == 10
    assert sum(len(modes) for modes in api._OUTCOME_TABLES.values()) == 20


def test_cached_metrics_match_fresh_recomputation() -> None:
    _load_cutoff_cache()
    for outcome_id in sorted(_OUTCOME_TABLES):
        for mode in ("raw", "bias_corrected"):
            frame = pd.DataFrame(_OUTCOME_TABLES[outcome_id][mode])
            for column in ("start_time", "publish_time", "forecast_source_start_time"):
                if column in frame:
                    frame[column] = pd.to_datetime(frame[column], utc=True)
            scored = frame.loc[frame["delivery_date"].between(
                WINDOW_START.isoformat(), WINDOW_END.isoformat()
            )].copy()
            fresh = summary(scored)
            cached = _SUMMARY_RANGE_CACHE[(outcome_id, mode, WINDOW_START, WINDOW_END)]
            assert fresh["mae_mw"] == pytest.approx(cached["mae_mw"])
            assert fresh["buffer_p90_mw"] == pytest.approx(cached["buffer_p90_mw"])
            assert api._bootstrap_buffer_ci(scored) == pytest.approx((
                cached["buffer_p90_ci_low_mw"], cached["buffer_p90_ci_high_mw"]
            ))
            payload = _OUTCOME_PAYLOADS[outcome_id][mode]
            for name, computed in (
                ("by_hour", by_hour(scored)),
                ("by_day", by_day(scored)),
                ("histogram", error_histogram(scored)),
            ):
                cached_rows = payload[name]
                pd.testing.assert_frame_equal(
                    computed.reset_index(drop=True),
                    pd.DataFrame(cached_rows).reset_index(drop=True),
                    check_dtype=False,
                    check_exact=False,
                    atol=1e-8,
                )
            fresh_horizon = by_horizon(api._accuracy_forecasts_for_outcome(outcome_id, mode))
            cached_horizon = pd.DataFrame(_HORIZON_PAYLOADS[(outcome_id, mode)])
            fresh_horizon["horizon_bucket"] = fresh_horizon["horizon_bucket"].astype(str)
            pd.testing.assert_frame_equal(
                fresh_horizon.reset_index(drop=True),
                cached_horizon.reset_index(drop=True),
                check_dtype=False,
                check_exact=False,
                atol=1e-8,
            )


def test_trailing_bias_uses_delivery_days_d_minus_8_through_d_minus_2() -> None:
    days = pd.date_range("2026-01-02", "2026-01-10", freq="D")
    history = pd.DataFrame({
        "delivery_date": [day.date().isoformat() for day in days],
        "forecast_mw": [float(index) for index in range(len(days))],
        "actual_mw": [0.0] * len(days),
    })

    correction = _trailing_bias_by_day(history, date(2026, 1, 10), date(2026, 1, 10))

    assert correction["2026-01-10"] == 3.0


def test_p90_bootstrap_interval_is_ordered_and_repeatable() -> None:
    frame = pd.DataFrame({
        "delivery_date": ["2026-01-02"] * 2 + ["2026-01-03"] * 2,
        "forecast_mw": [110.0, 90.0, 120.0, 100.0],
        "actual_mw": [100.0] * 4,
        "horizon_h": [16.0] * 4,
        "forecast_source_start_time": pd.to_datetime([
            "2026-01-02T00:00:00Z", "2026-01-02T00:00:00Z",
            "2026-01-03T00:00:00Z", "2026-01-03T00:00:00Z",
        ], utc=True),
        "publish_time": pd.to_datetime([
            "2026-01-01T08:00:00Z", "2026-01-01T08:00:00Z",
            "2026-01-02T08:00:00Z", "2026-01-02T08:00:00Z",
        ], utc=True),
    })

    first = _bootstrap_buffer_ci(frame, draws=20)
    second = _bootstrap_buffer_ci(frame, draws=20)

    assert first == second
    assert first[0] is not None and first[1] is not None
    assert first[0] <= first[1]


def test_trailing_correction_does_not_use_actuals_after_d_minus_two() -> None:
    days = pd.date_range("2026-01-02", "2026-01-10", freq="D")
    history = pd.DataFrame({
        "delivery_date": [day.date().isoformat() for day in days],
        "forecast_mw": [100.0 + index for index in range(len(days))],
        "actual_mw": [100.0] * len(days),
    })
    original_correction = _trailing_bias_by_day(history, date(2026, 1, 10), date(2026, 1, 10))
    original_corrected_forecast = history.loc[history["delivery_date"] == "2026-01-10", "forecast_mw"] - original_correction["2026-01-10"]

    perturbed = history.copy()
    perturbed.loc[perturbed["delivery_date"].isin(["2026-01-09", "2026-01-10"]), "actual_mw"] += 5000.0
    changed_correction = _trailing_bias_by_day(perturbed, date(2026, 1, 10), date(2026, 1, 10))
    changed_corrected_forecast = perturbed.loc[perturbed["delivery_date"] == "2026-01-10", "forecast_mw"] - changed_correction["2026-01-10"]

    assert changed_correction == original_correction
    pd.testing.assert_series_equal(changed_corrected_forecast, original_corrected_forecast)


def test_paired_bootstrap_compares_the_same_delivery_day_resamples() -> None:
    raw = pd.DataFrame({
        "delivery_date": ["2026-01-02", "2026-01-02", "2026-01-03", "2026-01-03"],
        "start_time": pd.to_datetime([
            "2026-01-02T00:00:00Z", "2026-01-02T00:30:00Z",
            "2026-01-03T00:00:00Z", "2026-01-03T00:30:00Z",
        ], utc=True),
        "forecast_mw": [110.0, 90.0, 120.0, 100.0],
        "actual_mw": [100.0] * 4,
    })
    corrected = raw.copy()
    corrected["forecast_mw"] = [105.0, 95.0, 105.0, 95.0]

    result = _paired_summary_deltas(raw, corrected, draws=20)

    assert result["raw_minus_corrected_mae_mw"] == 5.0
    assert result["raw_minus_corrected_buffer_p90_mw"] > 0
    assert result["raw_minus_corrected_mae_ci_low_mw"] <= result["raw_minus_corrected_mae_ci_high_mw"]
    assert result["raw_minus_corrected_buffer_p90_ci_low_mw"] <= result["raw_minus_corrected_buffer_p90_ci_high_mw"]


def test_cutoffs_in_one_publish_interval_return_identical_data() -> None:
    early_cutoff = time(8, 0)
    later_cutoff = time(9, 0)
    assert _outcome_id(early_cutoff) == _outcome_id(later_cutoff)

    early_summary = accuracy_summary(WINDOW_START, WINDOW_END, early_cutoff, "raw")
    later_summary = accuracy_summary(WINDOW_START, WINDOW_END, later_cutoff, "raw")
    early_summary.pop("cutoff")
    later_summary.pop("cutoff")
    assert early_summary == later_summary

    early_day = day_view(date(2026, 1, 15), early_cutoff, "raw")
    later_day = day_view(date(2026, 1, 15), later_cutoff, "raw")
    assert [point["publish_time"] for point in early_day["points"]] == [
        point["publish_time"] for point in later_day["points"]
    ]
