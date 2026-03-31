"""
MA5 突破策略 - 配置文件
======================
修改此文件以调整回测参数

作者：Shawn
日期：2026-03-31
"""


# ========== 股票配置 ==========
# 要回测的股票（可修改）
VT_SYMBOL = "002202.SZSE"     # vnpy 格式
TS_CODE = "002202.SZ"          # Tushare 格式
STOCK_NAME = "金风科技"


# ========== 回测配置 ==========
START_DATE = "20230101"        # 回测开始日期
END_DATE = "20251231"          # 回测结束日期
INITIAL_CAPITAL = 1000000      # 初始资金（元）


# ========== 策略参数 ==========
# 可在回测时调整这些参数
STRATEGY_PARAMS = {
    "breakout_threshold": 0.01,    # 突破确认阈值 1%
    "stop_loss_rate": 0.10,        # 固定止损 10%
    "volume_ratio": 1.0,           # 成交量倍数（>5 日均量）
    "max_positions": 1,            # 最大持仓数
    "price_add": 0.05,             # 下单价格调整 5%
}


# ========== 数据配置 ==========
# Tushare 相关配置
DATA_PATH = "data/tushare"         # 数据缓存路径
USE_CACHE = True                   # 是否使用缓存数据


# ========== 备选股票池 ==========
# 快速切换测试股票
STOCK_POOL = {
    "金风科技": {"vt": "002202.SZSE", "ts": "002202.SZ"},
    "贵州茅台": {"vt": "600519.SSE", "ts": "600519.SH"},
    "宁德时代": {"vt": "300750.SZSE", "ts": "300750.SZ"},
    "中国平安": {"vt": "601318.SSE", "ts": "601318.SH"},
    "招商银行": {"vt": "600036.SSE", "ts": "600036.SH"},
}


def get_stock_config(stock_name: str) -> dict:
    """获取股票配置"""
    if stock_name in STOCK_POOL:
        return STOCK_POOL[stock_name]
    raise ValueError(f"未知股票：{stock_name}")
