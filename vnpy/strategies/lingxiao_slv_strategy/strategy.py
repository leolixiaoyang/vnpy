"""
Lingxiao 的 SLV 两层模型动量策略复现。

根据截图信息做高保真近似实现：
- 使用离线生成的 0-5 强度信号作为主输入
- 单资产（SLV）执行，信号强时提高目标仓位
- 叠加止损、跟踪止盈、最长持有期控制
"""

from vnpy.trader.constant import Direction
from vnpy.trader.object import BarData, TradeData
from vnpy.trader.utility import round_to

from vnpy.alpha import AlphaStrategy


class LingxiaoSlvStrategy(AlphaStrategy):
    """SLV 单资产强度信号策略"""

    buy_threshold: float = 3.5
    strong_buy_threshold: float = 4.5
    exit_threshold: float = 2.0
    stop_loss_rate: float = 0.06
    trailing_stop_rate: float = 0.08
    max_hold_days: int = 15
    cash_ratio: float = 0.95
    min_volume: int = 1
    price_add: float = 0.01

    def on_init(self) -> None:
        """策略初始化"""
        self.buy_price: float = 0.0
        self.high_price: float = 0.0
        self.holding_days: int = 0
        self.write_log("Lingxiao SLV 策略初始化")

    def on_trade(self, trade: TradeData) -> None:
        """成交回调"""
        if trade.direction == Direction.LONG:
            self.buy_price = trade.price
            self.high_price = trade.price
            self.holding_days = 0
            self.write_log(f"开仓: {trade.vt_symbol} @ {trade.price:.2f}")
        elif trade.direction == Direction.SHORT:
            self.buy_price = 0.0
            self.high_price = 0.0
            self.holding_days = 0
            self.write_log(f"平仓: {trade.vt_symbol} @ {trade.price:.2f}")

    def on_bars(self, bars: dict[str, BarData]) -> None:
        """K 线回调"""
        if not bars:
            return

        signal_df = self.get_signal()
        if signal_df.is_empty():
            return

        for vt_symbol, bar in bars.items():
            symbol_signal = signal_df.filter(signal_df["vt_symbol"] == vt_symbol)
            if symbol_signal.is_empty():
                continue

            signal = float(symbol_signal["signal"][0])
            position = self.get_pos(vt_symbol)

            if position > 0:
                self.holding_days += 1
                self.high_price = max(self.high_price, bar.high_price)

                profit_rate = (bar.close_price - self.buy_price) / self.buy_price if self.buy_price else 0.0
                drawdown = (self.high_price - bar.close_price) / self.high_price if self.high_price else 0.0

                should_exit = False
                reason = ""

                if profit_rate <= -self.stop_loss_rate:
                    should_exit = True
                    reason = "止损"
                elif drawdown >= self.trailing_stop_rate and profit_rate > 0:
                    should_exit = True
                    reason = "回撤止盈"
                elif self.holding_days >= self.max_hold_days:
                    should_exit = True
                    reason = "超期卖出"
                elif signal <= self.exit_threshold:
                    should_exit = True
                    reason = f"信号走弱({signal:.1f})"

                if should_exit:
                    self.set_target(vt_symbol, 0)
                    self.write_log(f"{reason}: {vt_symbol}")
                    continue

            if signal >= self.buy_threshold:
                cash = self.get_cash_available()
                strength_ratio = min(signal / 5.0, 1.0)

                if signal >= self.strong_buy_threshold:
                    strength_ratio = max(strength_ratio, 0.9)

                target_value = cash * self.cash_ratio * strength_ratio + position * bar.close_price
                target_volume = round_to(target_value / bar.close_price, self.min_volume)
                self.set_target(vt_symbol, target_volume)
                self.write_log(f"信号做多({signal:.1f}): {vt_symbol} 目标仓位 {target_volume}")
            elif position <= 0:
                self.set_target(vt_symbol, 0)

        self.execute_trading(bars, price_add=self.price_add)