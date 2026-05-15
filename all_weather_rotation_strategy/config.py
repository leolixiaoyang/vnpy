from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


ROOT_PATH: Path = Path(__file__).resolve().parents[2]
DATA_PATH: Path = ROOT_PATH / "data" / "tushare" / "all_weather_rotation"
RESULT_PATH: Path = ROOT_PATH / "data" / "tushare" / "all_weather_rotation" / "results"

# 回测区间
START_DATE: str = "2018-01-01"
END_DATE: str = "2026-04-30"

# 账户参数
INITIAL_CAPITAL: float = 1_000_000
MIN_TRADE_VOLUME: int = 100
CASH_USAGE_RATIO: float = 0.95
BUY_PRICE_SLIPPAGE: float = 0.05
SELL_PRICE_SLIPPAGE: float = 0.05

# 交易成本（与原策略基本一致）
OPEN_COMMISSION: float = 0.0003
CLOSE_COMMISSION: float = 0.0003
CLOSE_TAX: float = 0.001

# 策略参数
STOCK_NUM: int = 3
LOOKBACK_DAYS: int = 10
STOP_LOSS_RATE: float = 0.08
MIN_LISTING_DAYS: int = 375

# 原策略中的外盘 ETF
FOREIGN_ETF: list[str] = [
    "518880.SH",
    "513030.SH",
    "513100.SH",
    "164824.SZ",
    "159866.SZ",
]

# 大小盘指数（同 JoinQuant 逻辑）
BIG_INDEX_CODE: str = "000300.SH"
SMALL_INDEX_CODE: str = "399101.SZ"

# 当指数成分获取失败时的兜底池
FALLBACK_BIG_POOL: list[str] = [
    "600519.SH",
    "600036.SH",
    "601318.SH",
    "600276.SH",
    "600887.SH",
    "600030.SH",
    "600000.SH",
    "601888.SH",
    "600309.SH",
    "601668.SH",
]

FALLBACK_SMALL_POOL: list[str] = [
    "000001.SZ",
    "000002.SZ",
    "000063.SZ",
    "000333.SZ",
    "000651.SZ",
    "000858.SZ",
    "002304.SZ",
    "002594.SZ",
    "300059.SZ",
    "300750.SZ",
]

# tinyshare token: 优先环境变量，未设置时使用默认值
TUSHARE_TOKEN: str = os.getenv(
    "TUSHARE_TOKEN",
    "bNP3yb6kn4CCht3IGVh96GjeRvh72t78FWDwPFe0n2yF2X0w89KsSFjOc54c8a35",
)


@dataclass
class RuntimeConfig:
    start_date: str = START_DATE
    end_date: str = END_DATE
    initial_capital: float = INITIAL_CAPITAL
    stock_num: int = STOCK_NUM
