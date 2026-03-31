"""
Alpha 回测撮合问题测试
====================
测试订单撮合逻辑，找出为什么订单没有成交

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
from vnpy.trader.constant import Interval, Exchange
from vnpy.trader.object import BarData

# 设置 Tushare
TUSHARE_TOKEN = os.getenv("TUSHARE_TOKEN", "a96ef9108067fe2b72a787c7d0e6a6974e6f05fd43fa3050497acdb4")
ts.set_token(TUSHARE_TOKEN)
pro = ts.pro_api()


class TestStrategy:
    """测试策略"""
    
    def __init__(self, *args, **kwargs):
        from vnpy.alpha import AlphaStrategy
        from collections import defaultdict
        
        self.strategy_engine = None
        self.strategy_name = ""
        self.vt_symbols = []
        self.pos_data = defaultdict(float)
        self.target_data = defaultdict(float)
        self.bar_count = 0
        self.order_count = 0
        self.trade_count = 0
    
    def on_init(self):
        print("[策略] 初始化")
    
    def on_trade(self, trade):
        self.trade_count += 1
        print(f"[策略] 成交 #{self.trade_count}: {trade.vt_symbol} {trade.direction.value} {trade.volume}@{trade.price}")
    
    def on_bars(self, bars):
        self.bar_count += 1
        
        if self.bar_count <= 3:
            print(f"[策略] on_bars #{self.bar_count}, 股票数：{len(bars)}")
            for vt_symbol, bar in list(bars.items())[:1]:
                print(f"  {vt_symbol}: O={bar.open_price:.2f} H={bar.high_price:.2f} L={bar.low_price:.2f} C={bar.close_price:.2f}")
        
        # 在第一个交易日尝试买入
        if self.bar_count == 1:
            for vt_symbol in bars:
                bar = bars[vt_symbol]
                
                # 测试不同的下单价格
                test_prices = {
                    "close * 1.01": bar.close_price * 1.01,
                    "close * 1.05": bar.close_price * 1.05,
                    "low * 1.01": bar.low_price * 1.01,
                    "high": bar.high_price,
                    "low": bar.low_price,
                }
                
                print(f"\n[策略] 测试下单价格 ({vt_symbol}):")
                for name, price in test_prices.items():
                    print(f"  {name}: {price:.2f}")
                
                # 使用较高的价格下单
                from vnpy.trader.utility import round_to
                price = bar.close_price * 1.05  # 高 5%
                volume = 100
                
                print(f"\n[策略] 下单：{vt_symbol} buy {volume}@{price:.2f}")
                
                # 直接调用 send_order
                self.buy(vt_symbol, price, volume)
    
    def buy(self, vt_symbol, price, volume):
        from vnpy.trader.constant import Direction, Offset
        self.order_count += 1
        print(f"[策略] 发送订单 #{self.order_count}: {vt_symbol} buy {volume}@{price:.2f}")
        
        # 调用引擎的 send_order
        vt_orderids = self.strategy_engine.send_order(
            self, vt_symbol, Direction.LONG, Offset.OPEN, price, volume
        )
        print(f"[策略] 订单 ID: {vt_orderids}")
    
    def set_target(self, vt_symbol, target):
        self.target_data[vt_symbol] = target
    
    def get_pos(self, vt_symbol):
        return self.pos_data[vt_symbol]
    
    def get_target(self, vt_symbol):
        return self.target_data[vt_symbol]
    
    def execute_trading(self, bars, price_add):
        from vnpy.trader.constant import Direction, Offset
        from vnpy.trader.utility import round_to
        
        for vt_symbol, bar in bars.items():
            target = self.get_target(vt_symbol)
            pos = self.get_pos(vt_symbol)
            diff = target - pos
            
            if diff > 0:
                order_price = bar.close_price * (1 + price_add)
                volume = round_to(diff, 100)
                
                if volume >= 100:
                    print(f"[策略] execute_trading: {vt_symbol} buy {volume}@{order_price:.2f}")
                    self.buy(vt_symbol, order_price, volume)


def main():
    print("=" * 60)
    print("Alpha 回测撮合问题测试")
    print("=" * 60)
    
    # 1. 准备数据
    print("\n步骤 1: 准备数据")
    
    vt_symbol = "000001.SZSE"
    symbol = "000001"
    exchange = Exchange.SZSE
    
    # 下载数据
    df = pro.daily(ts_code="000001.SZ", start_date="20250101", end_date="20250131")
    if df is None or len(df) == 0:
        print("没有数据")
        return
    
    df = pl.DataFrame(df)
    print(f"下载 {len(df)} 条记录")
    
    # 创建 BarData
    bars = []
    for row in df.iter_rows(named=True):
        bar = BarData(
            symbol=symbol,
            exchange=exchange,
            datetime=datetime.strptime(row["trade_date"], "%Y%m%d"),
            interval=Interval.DAILY,
            open_price=row["open"],
            high_price=row["high"],
            low_price=row["low"],
            close_price=row["close"],
            volume=row["vol"],
            turnover=row["amount"],
            gateway_name="tushare"
        )
        bars.append(bar)
    
    # 2. 创建 Lab
    print("\n步骤 2: 创建 Lab")
    
    lab_path = Path(__file__).parent.parent / "lab_data" / "test_match"
    lab = AlphaLab(str(lab_path))
    
    # 保存数据
    lab.save_bar_data(bars)
    print(f"已保存 {len(bars)} 条 K 线")
    
    # 配置合约
    lab.add_contract_setting(
        vt_symbol=vt_symbol,
        long_rate=0.0003,
        short_rate=0.0013,
        size=100,
        pricetick=0.01
    )
    print(f"已配置合约 {vt_symbol}")
    
    # 3. 创建回测引擎
    print("\n步骤 3: 创建回测引擎")
    
    engine = BacktestingEngine(lab)
    
    engine.set_parameters(
        vt_symbols=[vt_symbol],
        interval=Interval.DAILY,
        start=datetime(2025, 1, 1),
        end=datetime(2025, 1, 31),
        capital=1000000,
    )
    
    # 4. 创建空信号
    print("\n步骤 4: 创建信号")
    
    signal_df = pl.DataFrame({
        "datetime": [datetime(2025, 1, 1)],
        "vt_symbol": [vt_symbol],
        "signal": [1.0]
    })
    print(f"信号数据：{len(signal_df)} 条")
    
    # 5. 添加策略
    print("\n步骤 5: 添加策略")
    
    # 动态修改 TestStrategy 的基类
    from vnpy.alpha import AlphaStrategy
    TestStrategy.__bases__ = (AlphaStrategy,)
    
    engine.add_strategy(TestStrategy, {}, signal_df)
    
    # 6. 加载数据
    print("\n步骤 6: 加载数据")
    
    engine.load_data()
    print(f"历史数据：{len(engine.history_data)} 条")
    print(f"交易日：{len(engine.dts)} 个")
    
    # 7. 运行回测
    print("\n步骤 7: 运行回测")
    
    engine.run_backtesting()
    
    # 8. 输出结果
    print("\n" + "=" * 60)
    print("回测结果")
    print("=" * 60)
    
    print(f"策略 bar_count: {engine.strategy.bar_count}")
    print(f"策略 order_count: {engine.strategy.order_count}")
    print(f"策略 trade_count: {engine.strategy.trade_count}")
    print(f"引擎订单数：{len(engine.limit_orders)}")
    print(f"引擎交易数：{len(engine.trades)}")
    
    if engine.trades:
        print("\n交易记录:")
        for vt_orderid, trade in engine.trades.items():
            print(f"  {trade.vt_symbol}: {trade.direction.value} {trade.volume}@{trade.price} ({trade.datetime})")
    
    if engine.limit_orders:
        print("\n订单记录:")
        for vt_orderid, order in list(engine.limit_orders.items())[:5]:
            print(f"  {order.vt_symbol}: {order.direction.value} {order.volume}@{order.price} status={order.status.value}")


if __name__ == "__main__":
    main()
