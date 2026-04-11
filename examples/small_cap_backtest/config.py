"""小市值杠铃策略回测配置。"""

from pathlib import Path

from vnpy.trader.constant import Interval


ROOT_PATH: Path = Path(__file__).resolve().parents[2]
LAB_PATH: Path = ROOT_PATH / "lab_data" / "small_cap"
SIGNAL_CACHE: Path = LAB_PATH / "signal" / "small_cap_signal.parquet"

# 股票池模式："static" 使用固定股票池，"dynamic" 使用中证500成分股
STOCK_POOL_MODE: str = "dynamic"  # 改成 "dynamic" 就会用中证500

# 固定股票池（仅当 STOCK_POOL_MODE="static" 时使用）
STATIC_STOCK_POOL: list[str] = [
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

# 动态股票池：中证1000成分股（当 STOCK_POOL_MODE="dynamic" 时使用）
DYNAMIC_INDEX_CODE: str = "000852.SH"  # 中证1000

def get_dynamic_stock_pool(token: str, index_code: str = DYNAMIC_INDEX_CODE) -> list[str]:
    """动态获取指数成分股作为股票池。"""
    import tinyshare as ts
    ts.set_token(token)
    pro = ts.pro_api()
    
    # 获取最新成分股
    df = pro.index_weight(index_code=index_code, start_date="20240101")
    if df is None or len(df) == 0:
        return STATIC_STOCK_POOL  # 失败时回退到固定池
    
    # 去重，取最新日期的成分股
    latest_date = df["trade_date"].max()
    latest_df = df[df["trade_date"] == latest_date]
    stock_pool = list(latest_df["con_code"].unique())
    
    print(f"动态股票池: {len(stock_pool)} 只 (来自 {index_code} 成分股)")
    return stock_pool

# 根据模式选择股票池
TS_STOCK_POOL: list[str] = STATIC_STOCK_POOL  # 默认值，运行时可能被更新

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
