"""Generate the endpoint cache shipped with the read-only API."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from backend.app.config import PROCESSED_DIR, WINDOW_END, WINDOW_START
from backend.app.main import (
    _BREAKPOINT_OUTCOME_IDS,
    _OUTCOME_BREAKPOINTS,
    _OUTCOME_PAYLOADS,
    _OUTCOME_SIGNATURES,
    _OUTCOME_TABLES,
    _HORIZON_PAYLOADS,
    _SUMMARY_RANGE_CACHE,
    _prepare_cutoff_cache,
    day_view,
)


def _records(frame: pd.DataFrame) -> list[dict[str, object]]:
    """Use pandas JSON conversion so missing values and timestamps stay JSON-safe."""
    return json.loads(frame.to_json(orient="records", date_format="iso", date_unit="s"))


def _json_value(value: object) -> object:
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, (pd.Timestamp,)):
        return value.isoformat()
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if hasattr(value, "item"):
        return value.item()
    return value


def build_cache() -> int:
    _prepare_cutoff_cache()
    cache_dir = PROCESSED_DIR / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    outcome_ids = sorted(_OUTCOME_TABLES)
    for outcome_id in outcome_ids:
        for mode in ("raw", "bias_corrected"):
            key = (outcome_id, mode, WINDOW_START, WINDOW_END)
            response = _SUMMARY_RANGE_CACHE[key]
            days = {
                day.isoformat(): day_view(day, _OUTCOME_BREAKPOINTS[
                    next(i for i, value in enumerate(_BREAKPOINT_OUTCOME_IDS) if value == outcome_id)
                ], mode)
                for day in pd.date_range(WINDOW_START, WINDOW_END, freq="D").date
            }
            data = {
                "outcome_id": outcome_id,
                "mode": mode,
                "decision_rows": _records(_OUTCOME_TABLES[outcome_id][mode]),
                "payload": _json_value(_OUTCOME_PAYLOADS[outcome_id][mode]),
                "horizon": _records(pd.DataFrame(_HORIZON_PAYLOADS[(outcome_id, mode)])),
                "summary_response": _json_value(response),
                "days": _json_value(days),
            }
            path = cache_dir / f"outcome-{outcome_id:02d}-{mode}.json"
            path.write_text(json.dumps(data, separators=(",", ":"), allow_nan=False), encoding="utf-8")

    signatures = []
    for signature, outcome_id in _OUTCOME_SIGNATURES.items():
        signatures.append({"outcome_id": outcome_id, "selected_publish_times": signature})
    manifest = {
        "breakpoints": [
            {"cutoff": cutoff.isoformat(), "outcome_id": outcome_id}
            for cutoff, outcome_id in zip(_OUTCOME_BREAKPOINTS, _BREAKPOINT_OUTCOME_IDS)
        ],
        "outcome_ids": outcome_ids,
        "selection_signatures": _json_value(signatures),
        "scored_delivery_days": (WINDOW_END - WINDOW_START).days + 1,
    }
    (cache_dir / "manifest.json").write_text(
        json.dumps(manifest, separators=(",", ":"), allow_nan=False), encoding="utf-8"
    )
    return len(outcome_ids)


if __name__ == "__main__":
    print(f"Built cache for {build_cache()} selection outcomes x 2 modes")
