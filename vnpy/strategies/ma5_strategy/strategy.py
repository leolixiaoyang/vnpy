"""
MA5 突破策略
============
策略逻辑：
- 向上突破 MA5 确认（>1%）+ 放量 → 次日开盘买入
- 向下突破 MA5 → 次日开盘卖出
- 固定止损 -10%

作者：Shawn
日期：2026-03-31
"""

from vnpy.trader.object import BarData, TradeData
from vnpy.trader.constant import Direction
from vnpy.trader.utility import round_to

from vnpy.alpha import AlphaStrategy


class MA5BreakoutStrategy(AlphaStrategy):
    """MA5 突破策略"""

    # ========== 策略参数 ==========
    breakout_threshold: float = 0.01    # 突破确认阈值 1%
    stop_loss_rate: float = 0.10        # 固定止损 10%
    volume_ratio: float = 1.0           # 成交量倍数（>5 日均量）
    max_positions: int = 1              # 最大持仓数（单只股票）
    price_add: float = 0.05             # 下单价格调整 5%

    def on_init(self) -> None:
        """策略初始化"""
        # 状态跟踪
        self.ma5 = 0.0
        self.vol_ma5 = 0.0
        self.holding = False
        self.cost_price = 0.0
        self.last_signal_date = None
        
        self.write_log("策略初始化")
        self.write_log(f"突破阈值：{self.breakout_threshold*100}%")
        self.write_log(f"止损：-{self.stop_loss_rate*100}%")

    def on_trade(self, trade: TradeData) -> None:
        """成交回调"""
        if trade.direction == Direction.LONG:
            self.cost_price = trade.price
            self.holding = True
            self.write_log(f"开仓：{trade.vt_symbol}, 价格：{trade.price}, 数量：{trade.volume}")
        
        elif trade.direction == Direction.SHORT:
            self.holding = False
            self.cost_price = 0.0
            self.write_log(f"平仓：{trade.vt_symbol}")

    def on_bars(self, bars: dict[str, BarData]) -> None:
        """K 线回调"""
        if not bars:
            return
        
        # 获取当前股票
        vt_symbol = list(bars.keys())[0]
        bar = bars[vt_symbol]
        
        # 计算 MA5 和成交量均线
        self._calculate_ma(bars)
        
        # 检查止损
        if self.holding and self.cost_price > 0:
            current_loss = (bar.close_price - self.cost_price) / self.cost_price
            if current_loss <= -self.stop_loss_rate:
                self._sell(bar, "止损")
                return
        
        # 检查卖出信号（向下跌破 MA5）
        if self.holding:
            if bar.close_price < self.ma5:
                self._sell(bar, "跌破 MA5")
                return
        
        # 检查买入信号（向上突破 MA5）
        if not self.holding:
            # 获取前一日数据（用于判断突破）
            prev_bar = self.get_prev_bar(vt_symbol)
            if prev_bar:
                prev_ma5 = self._calculate_prev_ma5(bars)
                
                # 突破条件
                break_up = (bar.close_price > self.ma5) and (prev_bar.close_price <= prev_ma5)
                break_confirmed = bar.close_price > self.ma5 * (1 + self.breakout_threshold)
                volume_confirmed = bar.volume > self.vol_ma5 * self.volume_ratio
                
                if break_up and break_confirmed and volume_confirmed:
                    self._buy(bar, "突破 MA5")

    def _calculate_ma(self, bars: dict[str, BarData]) -> None:
        """计算 MA5 和成交量均线"""
        # 获取最近 5 根 K 线
        history = self.get_history_bars(list(bars.keys())[0], 5)
        
        if len(history) >= 5:
            closes = [bar.close_price for bar in history]
            volumes = [bar.volume for bar in history]
            
            self.ma5 = sum(closes) / 5
            self.vol_ma5 = sum(volumes) / 5

    def _calculate_prev_ma5(self, bars: dict[str, BarData]) -> float:
        """计算前一日 MA5"""
        history = self.get_history_bars(list(bars.keys())[0], 6)
        
        if len(history) >= 6:
            closes = [bar.close_price for bar in history[:-1]]  # 排除最新一根
            return sum(closes) / 5
        
        return 0.0

    def _buy(self, bar: BarData, reason: str) -> None:
        """买入"""
        cash = self.get_cash_available()
        
        # 全仓买入
        buy_value = cash * 0.99  # 保留 1% 现金用于手续费
        buy_volume = round_to(buy_value / bar.close_price, 100)
        
        if buy_volume >= 100:
            self.set_target(bar.vt_symbol, buy_volume)
            self.write_log(f"{reason}: 买入 {buy_volume}股 @ {bar.close_price:.2f}")

    def _sell(self, bar: BarData, reason: str) -> None:
        """卖出"""
        self.set_target(bar.vt_symbol, 0)
        self.write_log(f"{reason}: 卖出")
