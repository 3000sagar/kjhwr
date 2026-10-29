"""Load the local processed snapshot once; the deployed API never fetches source data."""

from functools import lru_cache

import pandas as pd

from backend.app.config import PROCESSED_DIR


@lru_cache(maxsize=1)
def load_data() -> tuple[pd.DataFrame, pd.DataFrame]:
    forecasts = pd.read_csv(PROCESSED_DIR / "forecasts.csv")
    actuals = pd.read_csv(PROCESSED_DIR / "actuals.csv")
    forecasts["start_time"] = pd.to_datetime(forecasts["start_time"], utc=True)
    forecasts["publish_time"] = pd.to_datetime(forecasts["publish_time"], utc=True)
    forecasts["forecast_mw"] = pd.to_numeric(forecasts["forecast_mw"], errors="raise")
    if "forecast_source_start_time" in forecasts:
        forecasts["forecast_source_start_time"] = pd.to_datetime(
            forecasts["forecast_source_start_time"], utc=True
        )
    actuals["start_time"] = pd.to_datetime(actuals["start_time"], utc=True)
    actuals["actual_mw"] = pd.to_numeric(actuals["actual_mw"], errors="raise")
    return forecasts, actuals
