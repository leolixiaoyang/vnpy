"""
昨日涨停策略 - 配置文件
======================
修改此文件以调整回测参数

作者：Shawn
日期：2026-03-31
"""

import os

# ========== 股票池配置 ==========
# 测试股票池（可修改）
TEST_STOCKS = [
    "000001.SZ",  # 平安银行
    "000002.SZ",  # 万科 A
    "000063.SZ",  # 中兴通讯
    "000333.SZ",  # 美的集团
    "000651.SZ",  # 格力电器
    "000858.SZ",  # 五粮液
    "002304.SZ",  # 洋河股份
    "002594.SZ",  # 比亚迪
    "300750.SZ",  # 宁德时代
    "300059.SZ",  # 东方财富
    "600000.SH",  # 浦发银行
    "600036.SH",  # 招商银行
    "600519.SH",  # 贵州茅台
    "601318.SH",  # 中国平安
]

# 转换为 vnpy 格式
VT_SYMBOLS = [
    ts.replace(".SZ", ".SZSE").replace(".SH", ".SSE")
    for ts in TEST_STOCKS
]


# ========== 回测配置 ==========
START_DATE = "20230101"        # 回测开始日期
END_DATE = "20251231"          # 回测结束日期
INITIAL_CAPITAL = 1000000      # 初始资金（元）


# ========== 策略参数 ==========
STRATEGY_PARAMS = {
    "max_positions": 10,           # 最大持仓数
    "stop_loss_rate": 0.05,        # 止损 5%
    "take_profit_rate": 0.15,      # 止盈 15%
    "trailing_stop_rate": 0.05,    # 回撤止盈 5%
    "max_hold_days": 5,            # 最多持有 5 天
    "min_volume": 100,             # 最小交易单位（手）
    "price_add": 0.05,             # 下单价格调整 5%
}


# ========== 数据配置 ==========
DATA_PATH = "data/tushare"         # 数据缓存路径
USE_CACHE = True                   # 是否使用缓存数据

# Tushare Token
TUSHARE_TOKEN = os.getenv(
    "TUSHARE_TOKEN",
    "a96ef9108067fe2b72a787c7d0e6a6974e6f05fd43fa3050497acdb4"
)


# ========== 涨停判定配置 ==========
LIMIT_UP_RATES = {
    "688": 0.20,    # 科创板
    "300": 0.20,    # 创业板
    "8": 0.30,      # 北交所
    "4": 0.30,      # 北交所
    "920": 0.30,    # 北交所
}
DEFAULT_LIMIT_UP_RATE = 0.10  # 主板默认 10%
ST_LIMIT_UP_RATE = 0.05       # ST 股票 5%
