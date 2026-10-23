"""Legacy names; credentials never have a source-code default."""
import os
from pathlib import Path
ROOT_PATH = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT_PATH / "data" / "all_weather"
RESULT_PATH = ROOT_PATH / "runs"
START_DATE = "2018-01-01"
END_DATE = "2026-04-30"
INITIAL_CAPITAL = 1_000_000
TUSHARE_TOKEN = os.getenv("TINYSHARE_TOKEN", "")
