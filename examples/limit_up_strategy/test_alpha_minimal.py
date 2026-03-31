"""
Alpha 策略最小化测试
====================
参考 vnpy 官方示例，创建一个最小化的可运行测试

作者：Shawn
日期：2026-03-31
"""

import os
from datetime import datetime, timedelta
from pathlib import Path

import polars as pl
import tushare as ts

from vnpy.alpha import AlphaLab
from vnpy.alpha.strategy import BacktestingEngine
from vnpy.trader.constant import Interval

# 设置 Tushare
TUSHARE_TOKEN = os.getenv("TUSHARE_TOKEN", "a96ef9108067fe2b72a787c7d0e6a6974e6f05fd43fa3050497acdb4")
ts.set_token(TUSHARE_TOKEN)
pro = ts.pro_api()


# ========== 策略定义 ==========
from collections import defaultdict
import polars as pl
from vnpy.trader.object import BarData, TradeData
from vnpy.trader.constant import Direction
from vnpy.trader.utility import round_to
from vnpy.alpha import AlphaStrategy


class LimitUpDemoStrategy(AlphaStrategy):
    """昨日涨停策略（简化演示版）"""

    max_positions: int = 5
    signal_threshold: float = 0.5  # 信号阈值

    def on_init(self) -> None:
        """初始化"""
        self.holding_days: dict = defaultdict(int)
        self.write_log("策略初始化")
        self.bar_count = 0

    def on_trade(self, trade: TradeData) -> None:
        """成交回调"""
        self.write_log(f"成交：{trade.vt_symbol} {trade.direction.value} {trade.volume}@{trade.price}")
        if trade.direction == Direction.SHORT:
            self.holding_days.pop(trade.vt_symbol, None)

    def on_bars(self, bars: dict[str, BarData]) -> None:
        """K 线回调"""
        self.bar_count += 1
        
        # 打印前几次回调用于调试
        if self.bar_count <= 3:
            self.write_log(f"on_bars 调用 #{self.bar_count}, 股票数：{len(bars)}")
        
        # 获取信号
        signal_df = self.get_signal()
        
        if self.bar_count <= 3:
            self.write_log(f"信号数据行数：{len(signal_df)}")
            if not signal_df.is_empty():
                active = signal_df.filter(pl.col("signal") > self.signal_threshold)
                self.write_log(f"有信号的股票数：{len(active)}")
        
        if signal_df.is_empty():
            return
        
        # 获取有信号的股票
        active_df = signal_df.filter(pl.col("signal") > self.signal_threshold)
        active_symbols = set(active_df["vt_symbol"])
        
        if self.bar_count <= 3 and active_symbols:
            self.write_log(f"活跃股票：{list(active_symbols)[:5]}")
        
        # 获取当前持仓
        pos_symbols = set([vt for vt, pos in self.pos_data.items() if pos > 0])
        
        # 买入：信号强且未持仓的股票
        buy_symbols = list(active_symbols - pos_symbols)[:self.max_positions]
        
        if buy_symbols:
            cash = self.get_cash_available()
            self.write_log(f"可用现金：{cash}, 准备买入：{buy_symbols}")
            
            buy_value = cash * 0.95 / len(buy_symbols)
            
            for vt_symbol in buy_symbols:
                if vt_symbol in bars:
                    price = bars[vt_symbol].close_price
                    if price > 0:
                        volume = round_to(buy_value / price, 100)
                        if volume >= 100:
                            self.set_target(vt_symbol, volume)
                            self.write_log(f"设置目标：{vt_symbol} = {volume}")
        
        # 执行交易
        self.execute_trading(bars, price_add=0.01)


# ========== 主流程 ==========

def main():
    print("=" * 50)
    print("Alpha 策略最小化测试")
    print("=" * 50)
    
    # 1. 准备数据
    print("\n步骤 1: 准备数据")
    
    data_path = Path(__file__).parent.parent.parent / "data" / "tushare"
    cache_file = data_path / "alpha_test_data.parquet"
    
    if cache_file.exists():
        print(f"使用缓存数据：{cache_file}")
        daily_df = pl.read_parquet(cache_file)
    else:
        # 下载数据
        test_symbols = ["000001.SZ", "000002.SZ", "000063.SZ", "000333.SZ", "000651.SZ"]
        
        end_date = datetime.now().strftime("%Y%m%d")
        start_date = (datetime.now() - timedelta(days=365)).strftime("%Y%m%d")
        
        all_data = []
        for ts_code in test_symbols:
            try:
                df = pro.daily(ts_code=ts_code, start_date=start_date, end_date=end_date)
                if df is not None and len(df) > 0:
                    df = pl.DataFrame(df)
                    df = df.with_columns(pl.lit(ts_code).alias("ts_code"))
                    all_data.append(df)
                    print(f"  ✓ {ts_code}: {len(df)} 条")
            except Exception as e:
                print(f"  ✗ {ts_code}: {e}")
        
        if not all_data:
            print("没有下载到数据")
            return
        
        daily_df = pl.concat(all_data)
        data_path.mkdir(parents=True, exist_ok=True)
        daily_df.write_parquet(cache_file)
    
    print(f"数据总量：{len(daily_df)} 条")
    
    # 2. 生成信号
    print("\n步骤 2: 生成信号")
    
    # 判断涨停
    def get_limit_rate(ts_code: str) -> float:
        ts_code_upper = ts_code.upper()
        if ts_code_upper.startswith("688") or ts_code_upper.startswith("300"):
            return 0.20
        else:
            return 0.10
    
    df = daily_df.clone()
    df = df.with_columns([
        pl.col("ts_code").map_elements(get_limit_rate, return_dtype=pl.Float64).alias("limit_rate"),
        (pl.col("pre_close") * (1 + pl.col("ts_code").map_elements(get_limit_rate, return_dtype=pl.Float64) - 0.005)).alias("limit_price")
    ])
    
    df = df.with_columns([
        ((pl.col("close") >= pl.col("limit_price")) & 
         (pl.col("close") == pl.col("high"))).alias("is_limit_up")
    ])
    
    # 转换为 vnpy 需要的信号格式
    # 关键：信号列必须是数值型，名为 "signal"
    signal_df = df.with_columns([
        pl.when(pl.col("is_limit_up") == True)
        .then(1.0)  # 涨停股票 signal=1
        .otherwise(0.0).alias("signal")  # 其他 signal=0
    ])
    
    signal_df = signal_df.rename({"ts_code": "vt_symbol", "trade_date": "datetime"})
    signal_df = signal_df.with_columns([
        pl.col("datetime").str.to_datetime("%Y%m%d"),
        pl.col("vt_symbol").str.to_uppercase(),
    ])
    
    # 选择需要的列
    signal_df = signal_df.select([
        "datetime", "vt_symbol", "signal"
    ])
    
    # 统计有信号的数据
    signal_count = signal_df.filter(pl.col("signal") > 0).height
    print(f"涨停信号数：{signal_count}")
    
    if signal_count > 0:
        print("\n涨停信号示例:")
        print(signal_df.filter(pl.col("signal") > 0).head())
    
    # 检查回测期内的信号
    test_period_signals = signal_df.filter(
        (pl.col("datetime") >= datetime(2025, 1, 1)) &
        (pl.col("datetime") <= datetime(2026, 3, 31)) &
        (pl.col("signal") > 0)
    )
    print(f"\n回测期内信号数：{len(test_period_signals)}")
    if len(test_period_signals) > 0:
        print(test_period_signals.head())
    else:
        print("警告：回测期内没有涨停信号！")
    
    # 3. 创建实验室
    print("\n步骤 3: 创建实验室")
    
    lab_path = Path(__file__).parent.parent.parent / "lab_data" / "alpha_test"
    lab = AlphaLab(str(lab_path))
    
    # 4. 保存 K 线数据
    print("\n步骤 4: 保存 K 线数据")
    
    from vnpy.trader.object import BarData
    from vnpy.trader.constant import Exchange
    
    # 从原始数据中获取 OHLC
    bars_df = daily_df.clone()
    bars_df = bars_df.rename({"ts_code": "vt_symbol", "trade_date": "datetime", "vol": "volume"})
    bars_df = bars_df.with_columns([
        pl.col("datetime").str.to_datetime("%Y%m%d"),
        pl.col("vt_symbol").str.to_uppercase(),
    ])
    
    for vt_symbol in bars_df["vt_symbol"].unique():
        symbol_df = bars_df.filter(pl.col("vt_symbol") == vt_symbol)
        
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
                open_price=row.get("open", 0) or 0,
                high_price=row.get("high", 0) or 0,
                low_price=row.get("low", 0) or 0,
                close_price=row.get("close", 0) or 0,
                volume=row.get("volume", 0) or 0,
                turnover=row.get("amount", 0) or 0,
                gateway_name="tushare"
            )
            bars.append(bar)
        
        lab.save_bar_data(bars)
    
    print(f"已保存 {len(bars_df['vt_symbol'].unique())} 只股票")
    
    # 5. 配置合约
    print("\n步骤 5: 配置合约")
    
    for vt_symbol in bars_df["vt_symbol"].unique():
        lab.add_contract_setting(
            vt_symbol=vt_symbol,
            long_rate=0.0003,
            short_rate=0.0013,
            size=100,
            pricetick=0.01
        )
    
    print(f"已配置 {len(bars_df['vt_symbol'].unique())} 只合约")
    
    # 6. 创建回测引擎
    print("\n步骤 6: 创建回测引擎")
    
    engine = BacktestingEngine(lab)
    
    vt_symbols = list(signal_df["vt_symbol"].unique())
    
    engine.set_parameters(
        vt_symbols=vt_symbols,
        interval=Interval.DAILY,
        start=datetime(2025, 1, 1),
        end=datetime(2026, 3, 31),
        capital=1000000,
    )
    
    print(f"股票池：{len(vt_symbols)} 只")
    print(f"回测期：2025-01-01 至 2026-03-31")
    
    # 7. 添加策略
    print("\n步骤 7: 添加策略")
    
    setting = {"max_positions": 3, "signal_threshold": 0.5}
    engine.add_strategy(LimitUpDemoStrategy, setting, signal_df)
    
    print(f"策略参数：{setting}")
    
    # 8. 运行回测
    print("\n步骤 8: 运行回测")
    
    engine.run_backtesting()
    
    # 9. 计算结果
    print("\n步骤 9: 计算结果")
    
    try:
        df = engine.calculate_result()
        stats = engine.calculate_statistics()
        
        print("\n" + "=" * 50)
        print("回测结果")
        print("=" * 50)
        
        for key, value in stats.items():
            print(f"{key}: {value}")
        
        # 保存结果
        result_path = data_path / "alpha_test_results.json"
        import json
        with open(result_path, "w", encoding="utf-8") as f:
            json.dump(stats, f, indent=2, ensure_ascii=False, default=str)
        print(f"\n结果已保存：{result_path}")
        
    except Exception as e:
        print(f"\n计算结果失败：{e}")
        
        # 检查交易记录
        print(f"\n交易记录数：{len(engine.trades)}")
        if engine.trades:
            print("交易记录:")
            for vt_orderid, trade in list(engine.trades.items())[:5]:
                print(f"  {trade.vt_symbol}: {trade.direction.value} {trade.volume}@{trade.price}")
        else:
            print("没有交易记录")


if __name__ == "__main__":
    main()
