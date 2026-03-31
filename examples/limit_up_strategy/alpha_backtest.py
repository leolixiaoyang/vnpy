"""
正式版回测 - 使用 LimitUpStrategy 类
=====================================
基于 vnpy alpha 回测引擎，使用策略类进行回测

作者：Shawn
日期：2026-03-31
"""

import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import polars as pl
import tushare as ts

# 添加策略路径
sys.path.insert(0, str(Path(__file__).parent))

from limit_up_alpha_strategy import LimitUpAlphaStrategy
from vnpy.alpha import AlphaLab, AlphaDataset, Segment
from vnpy.alpha.strategy.backtesting import BacktestingEngine
from vnpy.trader.constant import Interval

# 设置 Tushare
TUSHARE_TOKEN = os.getenv("TUSHARE_TOKEN", "a96ef9108067fe2b72a787c7d0e6a6974e6f05fd43fa3050497acdb4")
ts.set_token(TUSHARE_TOKEN)
pro = ts.pro_api()


def download_data():
    """下载测试数据"""
    print("=" * 50)
    print("步骤 1: 下载数据")
    print("=" * 50)
    
    # 检查是否有缓存数据
    data_path = Path(__file__).parent.parent.parent / "data" / "tushare"
    cache_file = data_path / "alpha_backtest_data.parquet"
    
    if cache_file.exists():
        print(f"使用缓存数据：{cache_file}")
        return pl.read_parquet(cache_file)
    
    # 选择 10 只活跃股票（避免频率限制）
    test_symbols = [
        "000001.SZ", "000002.SZ", "000063.SZ", "000333.SZ", "000651.SZ",
        "000858.SZ", "002304.SZ", "002594.SZ", "300750.SZ", "300059.SZ",
    ]
    
    # 下载 2 年数据
    end_date = datetime.now().strftime("%Y%m%d")
    start_date = (datetime.now() - timedelta(days=730)).strftime("%Y%m%d")
    
    print(f"下载区间：{start_date} 至 {end_date}")
    
    all_data = []
    
    for ts_code in test_symbols:
        try:
            df = pro.daily(ts_code=ts_code, start_date=start_date, end_date=end_date)
            if df is not None and len(df) > 0:
                df = pl.DataFrame(df)
                df = df.with_columns(pl.lit(ts_code).alias("ts_code"))
                all_data.append(df)
                print(f"  ✓ {ts_code}: {len(df)} 条")
            # 避免频率限制
            import time
            time.sleep(1.5)
        except Exception as e:
            print(f"  ✗ {ts_code}: {e}")
    
    if not all_data:
        return None
    
    result = pl.concat(all_data)
    print(f"\n总计：{len(result)} 条记录")
    
    # 保存
    data_path.mkdir(parents=True, exist_ok=True)
    result.write_parquet(cache_file)
    
    return result


def generate_signal_data(daily_df: pl.DataFrame) -> pl.DataFrame:
    """
    生成策略信号数据
    包含：vt_symbol, datetime, is_limit_up, market_cap 等字段
    """
    print("\n" + "=" * 50)
    print("步骤 2: 生成涨停信号")
    print("=" * 50)
    
    df = daily_df.clone()
    
    # 判断涨停幅度
    def get_limit_rate(ts_code: str) -> float:
        ts_code_upper = ts_code.upper()
        if ts_code_upper.startswith("688"):
            return 0.20
        elif ts_code_upper.startswith("300"):
            return 0.20
        elif ts_code_upper.startswith("8") or ts_code_upper.startswith("4"):
            return 0.30
        else:
            return 0.10
    
    # 计算涨停价
    df = df.with_columns([
        pl.col("ts_code").map_elements(get_limit_rate, return_dtype=pl.Float64).alias("limit_rate"),
        (pl.col("pre_close") * (1 + pl.col("ts_code").map_elements(get_limit_rate, return_dtype=pl.Float64) - 0.005)).alias("limit_price")
    ])
    
    # 判断涨停
    df = df.with_columns([
        ((pl.col("close") >= pl.col("limit_price")) & 
         (pl.col("close") == pl.col("high"))).alias("is_limit_up")
    ])
    
    # 转换格式
    df = df.rename({"ts_code": "vt_symbol", "trade_date": "datetime"})
    df = df.with_columns([
        pl.col("datetime").str.to_datetime("%Y%m%d"),
        pl.col("vt_symbol").str.to_uppercase(),
        (pl.col("close") * pl.col("vol") * 100).alias("market_cap")  # 估算市值
    ])
    
    # 统计
    limit_up_count = df.filter(pl.col("is_limit_up") == True).height
    print(f"涨停记录数：{limit_up_count}")
    
    return df


def run_alpha_backtest(signal_df: pl.DataFrame):
    """
    使用 vnpy alpha 回测引擎运行回测
    """
    print("\n" + "=" * 50)
    print("步骤 3: 运行 Alpha 回测")
    print("=" * 50)
    
    # 创建实验室
    workspace = Path(__file__).parent.parent.parent
    lab_path = workspace / "lab_data" / "limit_up_alpha"
    
    lab = AlphaLab(str(lab_path))
    
    # 添加合约配置（A 股股票）
    print("\n配置合约参数...")
    for vt_symbol in signal_df["vt_symbol"].unique():
        lab.add_contract_setting(
            vt_symbol=vt_symbol,
            long_rate=0.0003,    # 买入手续费 万分之三
            short_rate=0.0013,   # 卖出手续费 万分之十三（含印花税）
            size=100,            # 1 手=100 股
            pricetick=0.01       # 最小价格变动
        )
    print(f"已配置 {len(signal_df['vt_symbol'].unique())} 只合约")
    
    # 保存 K 线数据到 lab
    bars_df = signal_df.select([
        "datetime", "vt_symbol", "open", "high", "low", "close", "vol", "amount"
    ]).rename({"vol": "volume"})
    
    # 转换并保存每日 K 线数据到 lab（用于回测引擎加载）
    print("\n保存 K 线数据到实验室...")
    from vnpy.trader.object import BarData
    from vnpy.trader.constant import Interval, Exchange
    
    for vt_symbol in bars_df["vt_symbol"].unique():
        symbol_df = bars_df.filter(pl.col("vt_symbol") == vt_symbol)
        
        # 提取 symbol 和 exchange
        if vt_symbol.endswith(".SZ"):
            symbol = vt_symbol.replace(".SZ", "")
            exchange = Exchange.SZSE
        elif vt_symbol.endswith(".SH"):
            symbol = vt_symbol.replace(".SH", "")
            exchange = Exchange.SSE
        else:
            continue
        
        bars = []
        for row in symbol_df.iter_rows(named=True):
            bar = BarData(
                symbol=symbol,
                exchange=exchange,
                datetime=row["datetime"],
                interval=Interval.DAILY,
                open_price=row["open"],
                high_price=row["high"],
                low_price=row["low"],
                close_price=row["close"],
                volume=row["volume"],
                turnover=row["amount"],
                gateway_name="tushare"
            )
            bars.append(bar)
        
        # 保存到 lab
        lab.save_bar_data(bars)
    
    print(f"已保存 {len(bars_df['vt_symbol'].unique())} 只股票的 K 线数据")
    
    # 准备信号数据
    signal_df_for_strategy = signal_df.select([
        "datetime", "vt_symbol", "is_limit_up", "market_cap"
    ])
    
    print(f"信号数据：{len(signal_df_for_strategy)} 条记录")
    print(f"日期范围：{signal_df_for_strategy['datetime'].min()} 至 {signal_df_for_strategy['datetime'].max()}")
    
    # ========== 配置回测引擎 ==========
    print("\n" + "=" * 50)
    print("步骤 4: 配置回测引擎")
    print("=" * 50)
    
    # 创建回测引擎（需要传入 lab）
    engine = BacktestingEngine(lab=lab)
    
    # 获取股票池
    vt_symbols = list(signal_df["vt_symbol"].unique())
    print(f"股票池：{len(vt_symbols)} 只股票")
    
    # 设置参数
    engine.set_parameters(
        vt_symbols=vt_symbols,
        interval=Interval.DAILY,
        start=datetime(2025, 1, 1),
        end=datetime(2026, 3, 31),
        capital=1000000,
    )
    
    # 添加策略（需要传入信号数据）
    engine.add_strategy(LimitUpAlphaStrategy, {}, signal_df_for_strategy)
    
    # ========== 运行回测 ==========
    print("\n" + "=" * 50)
    print("步骤 5: 运行回测")
    print("=" * 50)
    
    try:
        engine.run_backtesting()
        
        # 计算结果
        df = engine.calculate_result()
        stats = engine.calculate_statistics()
        
        # 输出结果
        print("\n" + "=" * 50)
        print("回测结果")
        print("=" * 50)
        
        for key, value in stats.items():
            print(f"{key}: {value}")
        
        # 保存结果
        result_path = workspace / "data" / "tushare" / "alpha_backtest_results.json"
        import json
        with open(result_path, "w", encoding="utf-8") as f:
            json.dump(stats, f, indent=2, ensure_ascii=False, default=str)
        print(f"\n结果已保存：{result_path}")
        
        return stats
        
    except Exception as e:
        print(f"\n回测失败：{e}")
        print("\n这可能是因为：")
        print("  1. 数据格式不符合 vnpy 要求")
        print("  2. AlphaStrategy 需要信号数据支持")
        print("  3. 需要更完整的数据准备流程")
        return None


def main():
    """主函数"""
    print("\n" + "=" * 50)
    print("昨日涨停策略 - Alpha 正式版回测")
    print("=" * 50)
    
    # 1. 下载数据
    daily_df = download_data()
    if daily_df is None:
        return
    
    # 2. 生成信号
    signal_df = generate_signal_data(daily_df)
    
    # 3. 运行回测
    results = run_alpha_backtest(signal_df)
    
    if results:
        print("\n" + "=" * 50)
        print("Alpha 回测完成！")
        print("=" * 50)


if __name__ == "__main__":
    main()
