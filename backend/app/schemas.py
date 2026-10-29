"""Typed response shapes keep the small API contract explicit."""

from datetime import date, datetime

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str


class ConfigResponse(BaseModel):
    cutoff: str
    timezone: str
    window_start: date
    window_end: date
    assumptions: list[str]


class DeliveryDay(BaseModel):
    delivery_date: date
    expected: int
    with_forecast: int


class DayPoint(BaseModel):
    start_time: datetime
    forecast_mw: float | None
    publish_time: datetime | None
    horizon_h: float | None
    actual_mw: float | None
    error_mw: float | None
    band_low_mw: float | None
    band_high_mw: float | None


class DaySummary(BaseModel):
    forecast_mwh: float
    actual_mwh: float
    peak_forecast_mw: float | None
    min_forecast_mw: float | None
    mae_mw: float | None
    bias_mw: float | None
    spread_mae_mw: float | None
    coverage: float


class DayResponse(BaseModel):
    delivery_date: date
    cutoff: str
    mode: str
    points: list[DayPoint]
    summary: DaySummary


class AccuracySummary(BaseModel):
    from_date: date
    to_date: date
    cutoff: str
    mode: str
    mae_mw: float | None
    rmse_mw: float | None
    bias_mw: float | None
    spread_mae_mw: float | None
    nmae: float | None
    buffer_p90_mw: float | None
    buffer_p90_ci_low_mw: float | None
    buffer_p90_ci_high_mw: float | None
    raw_minus_corrected_mae_mw: float
    raw_minus_corrected_mae_ci_low_mw: float
    raw_minus_corrected_mae_ci_high_mw: float
    raw_minus_corrected_buffer_p90_mw: float
    raw_minus_corrected_buffer_p90_ci_low_mw: float
    raw_minus_corrected_buffer_p90_ci_high_mw: float
    ci_level: float
    ci_method: str
    n_hourly_forecasts: int
    n_half_hour_points: int
    coverage: float


class HourMetric(BaseModel):
    hour: int
    mae_mw: float
    bias_mw: float
    spread_mae_mw: float
    q10: float
    q90: float
    n_hourly_forecasts: int


class DayMetric(BaseModel):
    delivery_date: date
    mae_mw: float
    bias_mw: float
    spread_mae_mw: float
    n_hourly_forecasts: int


class HorizonMetric(BaseModel):
    horizon_bucket: str
    mae_mw: float
    bias_mw: float
    spread_mae_mw: float
    n_hourly_forecasts: int


class HistogramBin(BaseModel):
    bin_low_mw: float
    bin_high_mw: float
    count: int
