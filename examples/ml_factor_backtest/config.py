"""ML 因子小市值策略回测配置。"""

from pathlib import Path

from vnpy.trader.constant import Interval


ROOT_PATH: Path = Path(__file__).resolve().parents[2]
LAB_PATH: Path = ROOT_PATH / "lab_data" / "ml_factor"
SIGNAL_CACHE: Path = LAB_PATH / "signal" / "ml_factor_signal.parquet"

# 股票池模式："static" 使用固定股票池，"dynamic" 使用中证500/中证1000成分股
STOCK_POOL_MODE: str = "dynamic"

# 固定股票池（仅当 STOCK_POOL_MODE="static" 时使用）
STATIC_STOCK_POOL: list[str] = [
    "000001.SZ", "000002.SZ", "000063.SZ", "000333.SZ",
    "000651.SZ", "000858.SZ", "002304.SZ", "002594.SZ",
    "600000.SH", "600036.SH", "600519.SH", "601318.SH",
]

# 动态股票池：中证1000成分股
DYNAMIC_INDEX_CODE: str = "000852.SH"  # 中证1000


def get_dynamic_stock_pool(index_code: str = DYNAMIC_INDEX_CODE) -> list[str]:
    """动态获取指数成分股作为股票池（使用 akshare）。"""
    import akshare as ak

    df = ak.index_stock_cons(symbol=index_code)
    df['symbol'] = df['品种代码'].apply(ak.stock_a_code_to_symbol)
    df['ts_code'] = df['symbol'].str[2:] + '.' + df['symbol'].str[:2].str.upper()
    # 去重保留唯一 ts_code
    stock_pool = df.drop_duplicates(subset=['ts_code'])['ts_code'].tolist()
    print(f"动态股票池: {len(stock_pool)} 只 (来自 {index_code} 成分股)")
    return stock_pool


TS_STOCK_POOL: list[str] = STATIC_STOCK_POOL

# 转换为 vnpy vt_symbol
VT_SYMBOLS: list[str] = [
    ts_code.replace(".SZ", ".SZSE").replace(".SH", ".SSE")
    for ts_code in TS_STOCK_POOL
]

START_DATE: str = "2018-01-01"
END_DATE: str = "2026-04-10"
INTERVAL: Interval = Interval.DAILY
INITIAL_CAPITAL: int = 1_000_000

USE_SIGNAL_CACHE: bool = True

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
    "stock_num": 1,
    "top_pct": 0.10,
    "min_listing_days": 375,
    "empty_period_start": "0405",
    "empty_period_end": "0430",
    "min_trade_volume": 100,
    "price_add": 0.05,
    "cash_use_ratio": 0.95,
    # ML 因子系数
    "group1_coeffs": [-3.89e-19, 6.05e-05, -0.000135, -0.000623],
    "group2_coeffs": [-0.00769, -0.00106, -0.000637],
    "group3_coeffs": [-0.000222, -0.000340, -1.24e-08],
    "group4_coeffs": [-0.00135, 0.00129, -0.00302, -0.000233, 0.000234],
    "group5_coeffs": [-6.69e-11, -0.000161, -0.000553, 9.17e-12],
}
