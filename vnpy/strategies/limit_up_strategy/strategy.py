"""
昨日涨停今日买入策略
====================
策略逻辑：
- T 日筛选涨停股票（根据板块区分涨停幅度）
- T+1 日开盘买入市值最大的前 N 只
- T+2 日及之后：动态止盈止损卖出

作者：Shawn
日期：2026-03-31
"""

from collections import defaultdict

from vnpy.trader.object import BarData, TradeData
from vnpy.trader.constant import Direction
from vnpy.trader.utility import round_to

from vnpy.alpha import AlphaStrategy


class LimitUpStrategy(AlphaStrategy):
    """昨日涨停今日买入策略"""

    # ========== 策略参数 ==========
    max_positions: int = 10           # 最大持仓数
    stop_loss_rate: float = 0.05      # 止损 5%
    take_profit_rate: float = 0.15    # 止盈 15%
    trailing_stop_rate: float = 0.05  # 回撤止盈 5%
    max_hold_days: int = 5            # 最多持有 5 天
    min_volume: int = 100             # 最小交易单位（手）
    price_add: float = 0.05           # 下单价格调整 5%

    def on_init(self) -> None:
        """策略初始化"""
        # 持仓跟踪
        self.holding_days: dict = defaultdict(int)
        self.buy_price: dict = {}
        self.high_price: dict = {}
        
        # 昨日涨停股票池
        self.prev_limit_up: dict = {}
        
        self.write_log("策略初始化")
        self.write_log(f"最大持仓：{self.max_positions}")
        self.write_log(f"止损：-{self.stop_loss_rate*100}%, 止盈：+{self.take_profit_rate*100}%")

    def on_trade(self, trade: TradeData) -> None:
        """成交回调"""
        if trade.direction == Direction.LONG:
            self.buy_price[trade.vt_symbol] = trade.price
            self.high_price[trade.vt_symbol] = trade.price
            self.holding_days[trade.vt_symbol] = 0
            self.write_log(f"开仓：{trade.vt_symbol}, 价格：{trade.price}")
        
        elif trade.direction == Direction.SHORT:
            if trade.vt_symbol in self.buy_price:
                profit = (trade.price - self.buy_price[trade.vt_symbol]) / self.buy_price[trade.vt_symbol]
                self.write_log(f"平仓：{trade.vt_symbol}, 盈亏：{profit*100:.2f}%")
                
                self.buy_price.pop(trade.vt_symbol, None)
                self.high_price.pop(trade.vt_symbol, None)
                self.holding_days.pop(trade.vt_symbol, None)

    def on_bars(self, bars: dict[str, BarData]) -> None:
        """K 线回调"""
        if not bars:
            return
        
        # 获取信号数据
        signal_df = self.get_signal()
        
        if signal_df.is_empty():
            return
        
        # 获取当前日期
        current_dt = self.strategy_engine.datetime
        
        # 筛选昨日涨停股票（按市值排序）
        limit_up_df = signal_df.filter(
            (signal_df["datetime"] == current_dt) & 
            (signal_df["signal"] > 0.5)
        ).sort("market_cap", descending=True)
        
        self.prev_limit_up = {
            row["vt_symbol"]: row["market_cap"]
            for row in limit_up_df.iter_rows(named=True)
        }
        
        # 更新持仓信息
        for vt_symbol in list(self.pos_data.keys()):
            if self.pos_data[vt_symbol] > 0:
                self.holding_days[vt_symbol] += 1
                if vt_symbol in bars:
                    self.high_price[vt_symbol] = max(
                        self.high_price.get(vt_symbol, 0),
                        bars[vt_symbol].high_price
                    )
        
        # 检查止盈止损
        sell_symbols = self._check_exit(bars)
        
        # 执行卖出
        for vt_symbol in sell_symbols:
            if vt_symbol in bars:
                self.set_target(vt_symbol, 0)
        
        # 检查买入
        current_pos = len([vt for vt, pos in self.pos_data.items() if pos > 0])
        can_buy = self.max_positions - current_pos
        
        if can_buy > 0 and self.prev_limit_up:
            buy_candidates = [
                vt for vt in self.prev_limit_up.keys()
                if vt not in self.pos_data or self.pos_data[vt] == 0
            ]
            
            buy_symbols = buy_candidates[:can_buy]
            
            if buy_symbols:
                cash = self.get_cash_available()
                buy_value = cash * 0.95 / len(buy_symbols)
                
                for vt_symbol in buy_symbols:
                    if vt_symbol in bars:
                        price = bars[vt_symbol].close_price
                        if price > 0:
                            volume = round_to(buy_value / price, self.min_volume)
                            if volume >= self.min_volume:
                                self.set_target(vt_symbol, volume)
                                self.write_log(f"买入：{vt_symbol} vol={volume} @ {price:.2f}")
        
        # 执行交易
        self.execute_trading(bars, price_add=self.price_add)

    def _check_exit(self, bars: dict[str, BarData]) -> list:
        """检查止盈止损条件"""
        sell_symbols = []
        
        for vt_symbol in list(self.pos_data.keys()):
            if self.pos_data[vt_symbol] <= 0 or vt_symbol not in bars:
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
                self.write_log(f"止损：{vt_symbol} {profit_rate*100:.2f}%")
                continue
            
            # 止盈
            if profit_rate >= self.take_profit_rate:
                sell_symbols.append(vt_symbol)
                self.write_log(f"止盈：{vt_symbol} {profit_rate*100:.2f}%")
                continue
            
            # 回撤止盈
            if profit_rate > 0 and drawdown >= self.trailing_stop_rate:
                sell_symbols.append(vt_symbol)
                self.write_log(f"回撤止盈：{vt_symbol}")
                continue
            
            # 超期
            if hold_days >= self.max_hold_days:
                sell_symbols.append(vt_symbol)
                self.write_log(f"超期卖出：{vt_symbol} {hold_days}天")
                continue
        
        return sell_symbols
