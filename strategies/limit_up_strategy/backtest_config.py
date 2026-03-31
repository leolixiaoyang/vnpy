"""
回测配置示例
============
演示如何使用 LimitUpStrategy 进行回测

作者：Shawn
日期：2026-03-31
"""

from datetime import datetime
from pathlib import Path

import polars as pl

from vnpy.alpha import AlphaLab, AlphaDataset, Segment, BacktestingEngine
from vnpy.alpha.strategy.backtesting import BacktestingEngine
from limit_up_strategy import LimitUpStrategy


def run_backtest():
    """运行回测"""
    
    # ========== 1. 配置路径 ==========
    workspace = Path(__file__).parent.parent.parent
    lab_path = workspace / "lab_data" / "limit_up_strategy"
    
    # ========== 2. 创建实验室 ==========
    lab = AlphaLab(str(lab_path))
    
    # ========== 3. 加载数据 ==========
    # 假设已经通过 data_downloader.py 下载了数据
    data_path = workspace / "data" / "tushare"
    daily_file = data_path / "daily_20240101_20241231.parquet"
    
    if not daily_file.exists():
        print(f"数据文件不存在：{daily_file}")
        print("请先运行 data_downloader.py 下载数据")
        return
    
    daily_df = pl.read_parquet(daily_file)
    
    # 转换数据格式为 vnpy 需要的格式
    # vnpy 需要：datetime, vt_symbol, open, high, low, close, volume, turnover, open_interest
    bars_df = daily_df.rename({
        "trade_date": "datetime",
        "ts_code": "vt_symbol"
    })
    
    bars_df = bars_df.with_columns([
        pl.col("datetime").str.to_datetime("%Y%m%d"),
        pl.col("vt_symbol").str.to_uppercase(),
    ])
    
    # 保存到 lab
    # 这里需要转换为 BarData 列表，简化处理直接保存 DataFrame
    
    # ========== 4. 创建数据集 ==========
    dataset = AlphaDataset(
        df=bars_df,
        train_period=("2024-01-01", "2024-03-31"),
        valid_period=("2024-04-01", "2024-06-30"),
        test_period=("2024-07-01", "2024-12-31"),
        process_type="append"
    )
    
    # ========== 5. 生成信号 ==========
    # 使用 TushareDataDownloader 生成每日信号
    from data_downloader import TushareDataDownloader
    
    downloader = TushareDataDownloader()
    
    # 为每个交易日生成信号
    # 实际使用时可以批量生成并保存
    
    # ========== 6. 配置回测引擎 ==========
    engine = BacktestingEngine()
    
    # 设置回测参数
    engine.set_parameters(
        vt_symbols=["000001.SZ", "000002.SZ", "600000.SH", "600036.SH"],  # 示例股票池
        interval="1d",
        start=datetime(2024, 7, 1),
        end=datetime(2024, 12, 31),
        rate=0.0003,      # 手续费率
        slippage=0.0,     # 滑点
        size=100,         # 合约乘数
        pricetick=0.01,   # 最小价格变动
        capital=1000000,  # 初始资金 100 万
    )
    
    # 添加策略
    engine.add_strategy(LimitUpStrategy, {})
    
    # ========== 7. 运行回测 ==========
    print("开始运行回测...")
    engine.run_backtesting()
    
    # ========== 8. 计算统计指标 ==========
    df = engine.calculate_result()
    stats = engine.calculate_statistics()
    
    # ========== 9. 输出结果 ==========
    print("\n" + "="*50)
    print("回测结果")
    print("="*50)
    
    for key, value in stats.items():
        print(f"{key}: {value}")
    
    # ========== 10. 可视化（可选） ==========
    # engine.show_chart()
    
    return stats


def run_with_signal():
    """使用预生成信号运行回测（推荐方式）"""
    
    workspace = Path(__file__).parent.parent.parent
    lab_path = workspace / "lab_data" / "limit_up_strategy"
    
    lab = AlphaLab(str(lab_path))
    
    # 加载预生成的信号
    signal_dates = ["20240701", "20240702", "20240703"]  # 示例
    
    for date in signal_dates:
        signal_df = lab.load_signal(f"signal_{date}")
        if signal_df is not None:
            print(f"加载信号 {date}: {len(signal_df)} 只股票")
    
    # TODO: 将信号与策略集成
    # 这需要在策略中正确实现 get_signal() 方法


if __name__ == "__main__":
    run_backtest()
