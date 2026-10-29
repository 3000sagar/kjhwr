"""Small set of settings shared by the API routes."""

from datetime import date, time
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT_DIR = Path(__file__).resolve().parents[2]
PROCESSED_DIR = ROOT_DIR / "data" / "processed"
LOCAL_ZONE = ZoneInfo("Europe/London")
DEFAULT_CUTOFF = time(9)
WINDOW_START = date(2026, 1, 2)
WINDOW_END = date(2026, 2, 1)

