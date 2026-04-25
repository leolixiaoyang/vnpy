"""多均线择时策略回测配置。"""

from pathlib import Path

from vnpy.trader.constant import Interval


ROOT_PATH: Path = Path(__file__).resolve().parents[2]
LAB_PATH: Path = ROOT_PATH / "lab_data" / "multi_ma"
DAILY_BAR_CACHE: Path = LAB_PATH / "daily_bars.parquet"

# 交易标的
TS_CODE: str = "600196.SH"  # 复星医药

# 回测参数
START_DATE: str = "2018-01-01"
END_DATE: str = "2026-04-10"
INTERVAL: Interval = Interval.DAILY
INITIAL_CAPITAL: int = 1_000_000

# Tushare token
TUSHARE_TOKEN: str = (
    "bNP3yb6kn4CCht3IGVh96GjeRvh72t78FWDwPFe0n2yF2X0w89KsSFjOc54c8a35"
)

# 回测合约手续费
CONTRACT_SETTINGS: dict = {
    "long_rate": 0.0003,
    "short_rate": 0.0013,
    "size": 1,
    "pricetick": 0.01,
}

# 策略参数
STRATEGY_PARAMS: dict = {
    "stock": "600196.SSE",
    "ma_periods": [5, 10, 20, 30],
    "struggle_threshold_10_20": 0.003,
    "struggle_threshold_20_30": 0.002,
    "cash_ratio": 0.99,
    "price_add": 0.05,
}
