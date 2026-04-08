"""Lingxiao A股策略复现配置 - 科创50ETF。"""

from pathlib import Path

from vnpy.trader.constant import Interval


ROOT_PATH: Path = Path(__file__).resolve().parents[2]
LAB_PATH: Path = ROOT_PATH / "lab_data" / "lingxiao_a"
SIGNAL_CACHE: Path = LAB_PATH / "signal" / "lingxiao_a_signal.parquet"

# 目标品种：科创50ETF
VT_SYMBOL: str = "588000.SSE"

# 参考品种：沪深300ETF、创业板ETF、上证指数ETF
REFERENCE_SYMBOLS: dict[str, str] = {
    "hs300": "510300.SSE",    # 华泰柏瑞沪深300ETF
    "cyb": "159915.SZSE",      # 易方达创业板ETF
    "szindex": "510210.SSE",  # 上证指数ETF
}

START_DATE: str = "2020-01-01"  # 科创50上市时间较晚
END_DATE: str = "2025-12-31"
INTERVAL: Interval = Interval.DAILY
INITIAL_CAPITAL: int = 100_000

PRIMARY_LOOKBACK: int = 150  # 增大以确保一级模型有足够训练数据
META_LOOKBACK: int = 200
RETRAIN_INTERVAL: int = 2000  # 只训练一次（数据约1244条）
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
    "min_volume": 100,  # A股最小交易单位为100股
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
    "long_rate": 0.0003,   # A股印花税+佣金
    "short_rate": 0.0,     # A股不支持卖空
    "size": 1,
    "pricetick": 0.001,
}