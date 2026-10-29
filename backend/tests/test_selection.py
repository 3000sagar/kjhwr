from datetime import time

import pandas as pd
import pytest

from backend.app.metrics import summary
from backend.app.selection import build_decision_table


TARGET = "2026-01-02T10:00:00Z"


def actuals_for_target() -> pd.DataFrame:
    return pd.DataFrame([{
        "start_time": TARGET,
        "settlement_date": "2026-01-02",
        "actual_mw": 100.0,
    }])


def forecast(publish_time: str, forecast_mw: float = 100.0) -> dict[str, object]:
    return {"start_time": TARGET, "publish_time": publish_time, "forecast_mw": forecast_mw}


def target_row(table: pd.DataFrame) -> pd.Series:
    return table.loc[table["start_time"] == pd.Timestamp(TARGET)].iloc[0]


def test_selects_latest_publish_at_or_before_cutoff() -> None:
    rows = [forecast("2026-01-01T06:00:00Z", 80), forecast("2026-01-01T08:00:00Z", 90)]
    table = build_decision_table(pd.DataFrame(rows), actuals_for_target(), start="2026-01-02", end="2026-01-02")
    assert target_row(table)["forecast_mw"] == 90
    assert target_row(table)["publish_time"] == pd.Timestamp("2026-01-01T08:00:00Z")


def test_includes_forecast_published_exactly_at_cutoff() -> None:
    table = build_decision_table(
        pd.DataFrame([forecast("2026-01-01T09:00:00Z", 95)]), actuals_for_target(),
        cutoff_time=time(9), start="2026-01-02", end="2026-01-02",
    )
    assert target_row(table)["forecast_mw"] == 95


def test_ignores_forecast_published_after_cutoff() -> None:
    rows = [forecast("2026-01-01T08:00:00Z", 90), forecast("2026-01-01T09:01:00Z", 120)]
    table = build_decision_table(pd.DataFrame(rows), actuals_for_target(), start="2026-01-02", end="2026-01-02")
    assert target_row(table)["forecast_mw"] == 90


def test_missing_forecast_is_nan_and_coverage_counts_gap() -> None:
    table = build_decision_table(pd.DataFrame(columns=["start_time", "publish_time", "forecast_mw"]), actuals_for_target(), start="2026-01-02", end="2026-01-02")
    assert pd.isna(target_row(table)["forecast_mw"])
    assert table["forecast_mw"].notna().sum() == 0
    assert len(table) == 48
    assert summary(table)["coverage"] == 0.0


def test_identical_duplicate_forecast_rows_are_collapsed() -> None:
    duplicate = forecast("2026-01-01T08:00:00Z", 90)
    table = build_decision_table(pd.DataFrame([duplicate, duplicate]), actuals_for_target(), start="2026-01-02", end="2026-01-02")
    assert target_row(table)["forecast_mw"] == 90


def test_conflicting_duplicate_forecasts_fail_loudly() -> None:
    rows = [forecast("2026-01-01T08:00:00Z", 90), forecast("2026-01-01T08:00:00Z", 91)]
    with pytest.raises(ValueError, match="Conflicting forecast values"):
        build_decision_table(pd.DataFrame(rows), actuals_for_target(), start="2026-01-02", end="2026-01-02")


def test_decision_table_masks_negative_horizon(monkeypatch: pytest.MonkeyPatch) -> None:
    import backend.app.selection as selection

    target_start = "2026-01-02T00:00:00Z"
    source = pd.DataFrame([{
        "start_time": target_start,
        "publish_time": "2026-01-02T00:30:00Z",
        "forecast_mw": 110.0,
    }])
    actuals = pd.DataFrame([{"start_time": target_start, "actual_mw": 100.0}])
    monkeypatch.setattr(selection, "_cutoff_utc", lambda *_args: pd.Timestamp("2026-01-02T01:00:00Z"))

    table = build_decision_table(source, actuals, start="2026-01-02", end="2026-01-02")
    assert not (table["horizon_h"] < 0).any()
    selected_point = table.loc[table["start_time"] == pd.Timestamp(target_start)].iloc[0]
    assert pd.isna(selected_point["forecast_mw"])
