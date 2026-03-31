"""
昨日涨停今日买入策略 - Alpha 回测版
====================================
基于 vnpy alpha 回测引擎的策略实现

作者：Shawn
日期：2026-03-31
"""

from collections import defaultdict
from datetime import datetime, timedelta

import polars as pl

from vnpy.trader.object import BarData, TradeData
from vnpy.trader.constant import Direction
from vnpy.trader.utility import round_to

from vnpy.alpha import AlphaStrategy


class LimitUpAlphaStrategy(AlphaStrategy):
    """昨日涨停今日买入策略（Alpha 版）"""

    # ========== 策略参数 ==========
    max_positions: int = 10           # 最大持仓数
    stop_loss_rate: float = 0.05      # 止损 5%
    take_profit_rate: float = 0.15    # 止盈 15%
    trailing_stop_rate: float = 0.05  # 回撤止盈 5%
    max_hold_days: int = 5            # 最多持有 5 天
    min_volume: int = 100             # 最小交易单位（手）
    price_add: float = 0.01           # 下单价格调整（1%）

    def on_init(self) -> None:
        """策略初始化"""
        # 持仓跟踪
        self.holding_days: dict[str, int] = defaultdict(int)
        self.buy_price: dict[str, float] = {}
        self.high_price: dict[str, float] = {}
        
        # 昨日涨停股票池
        self.prev_limit_up: dict[str, float] = {}  # {vt_symbol: market_cap}
        
        self.write_log("策略初始化完成")
        self.write_log(f"最大持仓数：{self.max_positions}")

    def on_trade(self, trade: TradeData) -> None:
        """成交回调"""
        vt_symbol = trade.vt_symbol
        
        if trade.direction == Direction.LONG:
            self.buy_price[vt_symbol] = trade.price
            self.high_price[vt_symbol] = trade.price
            self.holding_days[vt_symbol] = 0
            self.write_log(f"开仓：{vt_symbol}, 价格：{trade.price}, 数量：{trade.volume}")
        
        elif trade.direction == Direction.SHORT:
            if vt_symbol in self.buy_price:
                buy_price = self.buy_price[vt_symbol]
                profit_rate = (trade.price - buy_price) / buy_price
                self.write_log(f"平仓：{vt_symbol}, 盈亏：{profit_rate*100:.2f}%")
                
                self.buy_price.pop(vt_symbol, None)
                self.high_price.pop(vt_symbol, None)
                self.holding_days.pop(vt_symbol, None)

    def on_bars(self, bars: dict[str, BarData]) -> None:
        """K 线回调"""
        if not bars:
            return
        
        current_dt = self.strategy_engine.datetime
        
        # ========== 1. 获取昨日涨停股票 ==========
        # 从信号数据中获取昨日涨停的股票
        signal_df = self.get_signal()
        
        if not signal_df.is_empty():
            # 筛选涨停股票，按市值排序
            limit_up_df = signal_df.filter(pl.col("is_limit_up") == True)
            limit_up_df = limit_up_df.sort("market_cap", descending=True)
            
            # 保存为字典
            self.prev_limit_up = {
                row["vt_symbol"]: row["market_cap"]
                for row in limit_up_df.iter_rows(named=True)
            }
            
            if self.prev_limit_up:
                self.write_log(f"昨日涨停股票数：{len(self.prev_limit_up)}")
        
        # ========== 2. 更新持仓信息 ==========
        pos_symbols = [vt for vt, pos in self.pos_data.items() if pos > 0]
        for vt_symbol in pos_symbols:
            self.holding_days[vt_symbol] += 1
            if vt_symbol in bars:
                self.high_price[vt_symbol] = max(
                    self.high_price.get(vt_symbol, 0),
                    bars[vt_symbol].high_price
                )
        
        # ========== 3. 检查止盈止损 ==========
        sell_symbols = []
        for vt_symbol in pos_symbols:
            if vt_symbol not in bars:
                continue
            
            bar = bars[vt_symbol]
            buy_price = self.buy_price.get(vt_symbol, 0)
            high_price = self.high_price.get(vt_symbol, 0)
            current_price = bar.close_price
            hold_days = self.holding_days.get(vt_symbol, 0)
            
            if buy_price <= 0:
                continue
            
            profit_rate = (current_price - buy_price) / buy_price
            drawdown = (high_price - current_price) / high_price if high_price > 0 else 0
            
            # 止损
            if profit_rate <= -self.stop_loss_rate:
                sell_symbols.append(vt_symbol)
                self.write_log(f"止损：{vt_symbol}, 盈亏：{profit_rate*100:.2f}%")
                continue
            
            # 止盈
            if profit_rate >= self.take_profit_rate:
                sell_symbols.append(vt_symbol)
                self.write_log(f"止盈：{vt_symbol}, 盈亏：{profit_rate*100:.2f}%")
                continue
            
            # 回撤止盈
            if profit_rate > 0 and drawdown >= self.trailing_stop_rate:
                sell_symbols.append(vt_symbol)
                self.write_log(f"回撤止盈：{vt_symbol}")
                continue
            
            # 超期
            if hold_days >= self.max_hold_days:
                sell_symbols.append(vt_symbol)
                self.write_log(f"超期卖出：{vt_symbol}")
                continue
        
        # ========== 4. 卖出 ==========
        for vt_symbol in sell_symbols:
            if vt_symbol in bars and self.pos_data[vt_symbol] > 0:
                bar = bars[vt_symbol]
                self.set_target(vt_symbol, 0)
        
        # ========== 5. 买入 ==========
        # 从昨日涨停股票中选择未持仓的
        current_pos = len([vt for vt, pos in self.pos_data.items() if pos > 0])
        can_buy_count = self.max_positions - current_pos
        
        if can_buy_count > 0 and self.prev_limit_up:
            # 过滤已持仓的
            buy_candidates = [
                vt for vt in self.prev_limit_up.keys()
                if vt not in self.pos_data or self.pos_data[vt] == 0
            ]
            
            # 选前 N 只
            buy_symbols = buy_candidates[:can_buy_count]
            
            # 计算每只股票的买入金额
            cash = self.strategy_engine.cash
            buy_value = cash * 0.95 / len(buy_symbols) if buy_symbols else 0
            
            for vt_symbol in buy_symbols:
                if vt_symbol not in bars:
                    continue
                
                bar = bars[vt_symbol]
                buy_price = bar.open_price
                
                if buy_price <= 0:
                    continue
                
                buy_volume = round_to(buy_value / buy_price, self.min_volume)
                
                if buy_volume >= self.min_volume:
                    self.set_target(vt_symbol, buy_volume)
                    self.write_log(f"买入：{vt_symbol}, 价格：{buy_price}, 数量：{buy_volume}")
        
        # ========== 6. 执行交易 ==========
        self.execute_trading(bars, price_add=self.price_add)
