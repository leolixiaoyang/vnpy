"""
自选股管理配置
==============
统一管理所有策略使用的自选股列表

作者：Shawn
日期：2026-03-31
"""

# ========== 自选股列表 ==========
# 格式：Tushare 代码（代码。交易所）
SELF_SELECT_STOCKS = [
    # 银行
    "000001.SZ",  # 平安银行
    "600000.SH",  # 浦发银行
    "600036.SH",  # 招商银行
    "601318.SH",  # 中国平安
    
    # 房地产
    "000002.SZ",  # 万科 A
    
    # 家电
    "000333.SZ",  # 美的集团
    "000651.SZ",  # 格力电器
    
    # 食品饮料
    "000858.SZ",  # 五粮液
    "002304.SZ",  # 洋河股份
    "600519.SH",  # 贵州茅台
    
    # 新能源汽车
    "002594.SZ",  # 比亚迪
    
    # 科技/通信
    "000063.SZ",  # 中兴通讯
    "300059.SZ",  # 东方财富
    "300750.SZ",  # 宁德时代
]

# ========== 股票池配置 ==========
# 按策略类型分类

# 1. 涨停策略股票池（适合做涨停接力）
LIMIT_UP_STOCKS = [
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

# 2. MA5 突破策略股票池（趋势股）
MA5_BREAKOUT_STOCKS = [
    "002202.SZ",  # 金风科技（默认测试股）
    "600519.SH",  # 贵州茅台
    "300750.SZ",  # 宁德时代
    "002594.SZ",  # 比亚迪
    "601318.SH",  # 中国平安
]


# ========== 代码转换工具 ==========

def to_vt_symbol(ts_code: str) -> str:
    """
    Tushare 代码转 vnpy 代码
    
    Args:
        ts_code: Tushare 代码（如 000001.SZ）
    
    Returns:
        vnpy 代码（如 000001.SZSE）
    """
    return ts_code.replace(".SZ", ".SZSE").replace(".SH", ".SSE")


def to_ts_code(vt_symbol: str) -> str:
    """
    vnpy 代码转 Tushare 代码
    
    Args:
        vt_symbol: vnpy 代码（如 000001.SZSE）
    
    Returns:
        Tushare 代码（如 000001.SZ）
    """
    return vt_symbol.replace(".SZSE", ".SZ").replace(".SSE", ".SH")


def get_stock_list(strategy: str = "all") -> list:
    """
    获取股票列表
    
    Args:
        strategy: 策略类型
            - "all": 全部自选股
            - "limit_up": 涨停策略股票池
            - "ma5": MA5 突破股票池
    
    Returns:
        股票列表（Tushare 格式）
    """
    if strategy == "limit_up":
        return LIMIT_UP_STOCKS
    elif strategy == "ma5":
        return MA5_BREAKOUT_STOCKS
    else:
        return SELF_SELECT_STOCKS


def get_vt_symbol_list(strategy: str = "all") -> list:
    """
    获取 vnpy 格式的股票列表
    
    Args:
        strategy: 策略类型
    
    Returns:
        股票列表（vnpy 格式）
    """
    ts_list = get_stock_list(strategy)
    return [to_vt_symbol(ts) for ts in ts_list]


# ========== 导入导出工具 ==========

def export_to_config(output_file: str = "config.py", strategy: str = "all"):
    """
    导出到策略配置文件
    
    Args:
        output_file: 输出文件名
        strategy: 策略类型
    """
    stocks = get_stock_list(strategy)
    
    config_content = f'''"""
策略配置文件 - 自动生成
======================
来源：stock_pool.py
策略：{strategy}
生成时间：{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
"""

# 股票池
TEST_STOCKS = [
'''
    
    for stock in stocks:
        config_content += f'    "{stock}",\n'
    
    config_content += ''']

# 转换为 vnpy 格式
VT_SYMBOLS = [
    ts.replace(".SZ", ".SZSE").replace(".SH", ".SSE")
    for ts in TEST_STOCKS
]
'''
    
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(config_content)
    
    print(f"已导出 {len(stocks)} 只股票到 {output_file}")


if __name__ == "__main__":
    # 测试
    print("=" * 60)
    print("自选股列表")
    print("=" * 60)
    
    print(f"\n全部自选股：{len(SELF_SELECT_STOCKS)} 只")
    for stock in SELF_SELECT_STOCKS:
        print(f"  {stock}")
    
    print(f"\n涨停策略股票池：{len(LIMIT_UP_STOCKS)} 只")
    for stock in LIMIT_UP_STOCKS:
        print(f"  {stock}")
    
    print(f"\nMA5 突破股票池：{len(MA5_BREAKOUT_STOCKS)} 只")
    for stock in MA5_BREAKOUT_STOCKS:
        print(f"  {stock}")
