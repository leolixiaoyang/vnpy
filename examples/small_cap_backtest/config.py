"""小市值杠铃策略回测配置。"""

from pathlib import Path

from vnpy.trader.constant import Interval


ROOT_PATH: Path = Path(__file__).resolve().parents[2]
LAB_PATH: Path = ROOT_PATH / "lab_data" / "small_cap"
SIGNAL_CACHE: Path = LAB_PATH / "signal" / "small_cap_signal.parquet"

# 默认股票池：可直接替换成你的中证500/全A样本
TS_STOCK_POOL: list[str] = [
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
    "600000.SH",
    "600036.SH",
    "600519.SH",
    "601318.SH",
    "601668.SH",
    "601888.SH",
    "600030.SH",
    "600276.SH",
    "600309.SH",
    "600887.SH",
]

VT_SYMBOLS: list[str] = [
    ts_code.replace(".SZ", ".SZSE").replace(".SH", ".SSE")
    for ts_code in TS_STOCK_POOL
]

# 杠铃资产中的黄金ETF
GOLD_TS_CODE: str = "518880.SH"
GOLD_VT_SYMBOL: str = "518880.SSE"

START_DATE: str = "2018-01-01"
END_DATE: str = "2026-04-10"
INTERVAL: Interval = Interval.DAILY
INITIAL_CAPITAL: int = 1_000_000

USE_SIGNAL_CACHE: bool = True

# Tushare token
TUSHARE_TOKEN: str = (
    "bNP3yb6kn4CCht3IGVh96GjeRvh72t78FWDwPFe0n2yF2X0w89KsSFjOc54c8a35"
)

# 回测合约手续费和最小跳动
CONTRACT_SETTINGS: dict = {
    "long_rate": 0.0003,
    "short_rate": 0.0013,
    "size": 1,
    "pricetick": 0.01,
}

STRATEGY_PARAMS: dict = {
    "stock_num": 20,
    "query_pool_num": 400,
    "small_cap_pool_num": 100,
    "rebalance_interval": 7,
    "empty_months": [1, 4],
    "enable_barbell": True,
    "stock_ratio": 0.5,
    "gold_ratio": 0.5,
    "gold_etf": GOLD_VT_SYMBOL,
    "min_listing_days": 365,
    "stop_loss_rate": 0.08,
    "min_trade_volume": 100,
    "price_add": 0.01,
    "pe_max": 50,
    "roe_min": 0.05,
    "vol20_max": 0.07,
    "trend_buffer_up": 0.98,
    "trend_buffer_ma": 0.97,
}
