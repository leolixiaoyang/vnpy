"""Lingxiao SLV 策略复现配置。"""

from pathlib import Path

from vnpy.trader.constant import Interval


ROOT_PATH: Path = Path(__file__).resolve().parents[2]
LAB_PATH: Path = ROOT_PATH / "lab_data" / "lingxiao_slv"
SIGNAL_CACHE: Path = LAB_PATH / "signal" / "lingxiao_slv_signal.parquet"

VT_SYMBOL: str = "SLV.ARCA"
REFERENCE_SYMBOLS: dict[str, str] = {
    "qqq": "QQQ.NASDAQ",
    "gold": "GLD.ARCA",
    "dollar": "UUP.ARCA",
}

START_DATE: str = "2010-01-01"
END_DATE: str = "2025-12-31"
INTERVAL: Interval = Interval.DAILY
INITIAL_CAPITAL: int = 100_000

PRIMARY_LOOKBACK: int = 60
META_LOOKBACK: int = 1000
RETRAIN_INTERVAL: int = 3
FORWARD_HORIZON_MIN: int = 5
FORWARD_HORIZON_MAX: int = 10

BUY_THRESHOLD: float = 3.5
EXIT_THRESHOLD: float = 2.0

STRATEGY_PARAMS: dict = {
    "buy_threshold": BUY_THRESHOLD,
    "strong_buy_threshold": 4.5,
    "exit_threshold": EXIT_THRESHOLD,
    "stop_loss_rate": 0.06,
    "trailing_stop_rate": 0.08,
    "max_hold_days": 15,
    "cash_ratio": 0.95,
    "min_volume": 1,
    "price_add": 0.01,
}

MODEL_PARAMS: dict = {
    "primary_lookback": PRIMARY_LOOKBACK,
    "meta_lookback": META_LOOKBACK,
    "retrain_interval": RETRAIN_INTERVAL,
    "forward_horizon_min": FORWARD_HORIZON_MIN,
    "forward_horizon_max": FORWARD_HORIZON_MAX,
}

CONTRACT_SETTINGS: dict = {
    "long_rate": 0.0005,
    "short_rate": 0.0005,
    "size": 1,
    "pricetick": 0.01,
}