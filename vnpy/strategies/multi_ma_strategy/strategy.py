"""
多均线择时策略
==============
克隆自聚宽文章：https://www.joinquant.com/post/570
标题：【简单的多均线择时策略】那个天台排队的孩子，我给你讲个故事

策略逻辑：
- 计算 MA5、MA10、MA20、MA30 四条均线
- 多头排列（MA5 > MA10 > MA20 > MA30）→ 满仓买入
- 空头排列（MA5 < MA10 < MA20）→ 清仓卖出
- 多头排列后死叉（MA5 下穿 MA10）→ 清仓卖出
- 空头排列后金叉（MA10 上穿 MA20）→ 满仓买入
- 均线纠缠时不操作（MA10/MA20 差异 < 0.3% 或 MA20/MA30 差异 < 0.2%）
"""

from vnpy.trader.object import BarData, TradeData
from vnpy.trader.utility import round_to

from vnpy.alpha import AlphaStrategy


class MultiMaStrategy(AlphaStrategy):
    """多均线择时策略"""

    # ========== 策略参数 ==========
    stock: str = ""                       # 交易标的
    ma_periods: list[int] = None          # 均线周期，默认 [5, 10, 20, 30]
    struggle_threshold_10_20: float = 0.003  # MA10/MA20 纠缠阈值
    struggle_threshold_20_30: float = 0.002  # MA20/MA30 纠缠阈值
    cash_ratio: float = 0.99              # 买入时资金使用比例
    price_add: float = 0.05               # 下单价格偏移

    def on_init(self) -> None:
        """策略初始化"""
        if self.ma_periods is None:
            self.ma_periods = [5, 10, 20, 30]

        self.ma_history: dict[int, list[float]] = {p: [] for p in self.ma_periods}
        self.bullish_history: list[bool] = []
        self.bearish_history: list[bool] = []

        self.write_log("多均线择时策略初始化")
        self.write_log(f"均线周期: {self.ma_periods}")

    def on_trade(self, trade: TradeData) -> None:
        """成交回调"""
        pos: float = self.get_pos(trade.vt_symbol)
        self.write_log(f"成交: {trade.vt_symbol}, 方向={trade.direction.value}, 价格={trade.price}, 数量={trade.volume}, 持仓={pos}")

    def on_bars(self, bars: dict[str, BarData]) -> None:
        """K 线回调"""
        if not bars:
            return

        vt_symbol = self.stock or list(bars.keys())[0]
        bar: BarData | None = bars.get(vt_symbol)
        if not bar:
            return

        self._update_ma_values(vt_symbol)

        # 需要足够的 MA 历史数据
        min_points = 3
        if any(len(self.ma_history[p]) < min_points for p in [5, 10, 20]):
            self.execute_trading(bars, price_add=self.price_add)
            return

        # 记录每日排列状态
        is_bull = self._is_bullish()
        is_bear = self._is_bearish()
        self.bullish_history.append(is_bull)
        self.bearish_history.append(is_bear)

        if len(self.bullish_history) < 2:
            self.execute_trading(bars, price_add=self.price_add)
            return

        current_pos: float = self.get_pos(vt_symbol)

        # ---------- 多头后死叉 → 卖出 ----------
        if current_pos > 0 and self._is_cross_down():
            self.set_target(vt_symbol, 0)
            self.write_log("死叉 清仓")

        # ---------- 空头后金叉 → 买入 ----------
        elif current_pos == 0 and self._is_cross_up():
            self._set_buy_target(bar, reason="金叉")

        # ---------- 多头排列 → 买入 ----------
        elif current_pos == 0 and is_bull:
            if self._is_struggle():
                self.execute_trading(bars, price_add=self.price_add)
                return
            self._set_buy_target(bar, reason="多头排列")

        # ---------- 空头排列 → 卖出 ----------
        elif current_pos > 0 and is_bear:
            self.set_target(vt_symbol, 0)
            self.write_log("空头排列 清仓")

        # ---------- 执行交易 ----------
        self.execute_trading(bars, price_add=self.price_add)

    # ==================== 均线计算 ====================

    def _update_ma_values(self, vt_symbol: str) -> None:
        """更新各周期均线值"""
        history = self.get_history_bars(vt_symbol, max(self.ma_periods))

        if len(history) >= max(self.ma_periods):
            closes = [b.close_price for b in history]

            for period in self.ma_periods:
                ma = sum(closes[-period:]) / period
                self.ma_history[period].append(ma)

    def _get_ma(self, period: int, offset: int = -1) -> float:
        """获取指定周期均线值，offset=-1 表示最新值"""
        return self.ma_history[period][offset]

    # ==================== 信号判断 ====================

    def _is_bullish(self) -> bool:
        """判断多头排列：MA5 > MA10 > MA20 > MA30"""
        required = [5, 10, 20, 30]
        for p in required:
            if len(self.ma_history[p]) < 1:
                return False

        return (self._get_ma(5) > self._get_ma(10) >
                self._get_ma(20) > self._get_ma(30))

    def _is_bearish(self) -> bool:
        """判断空头排列：MA5 < MA10 < MA20"""
        required = [5, 10, 20]
        for p in required:
            if len(self.ma_history[p]) < 1:
                return False

        return self._get_ma(5) < self._get_ma(10) < self._get_ma(20)

    def _is_cross_down(self) -> bool:
        """
        多头排列后死叉：
        - 前一天处于多头排列
        - MA5 下穿 MA10（前一天 MA5>MA10，今天 MA5<MA10）
        """
        if len(self.ma_history[5]) < 2 or len(self.ma_history[10]) < 2:
            return False

        was_bullish = self.bullish_history[-2]

        cross = (self._get_ma(5, -2) > self._get_ma(10, -2) and
                 self._get_ma(5, -1) < self._get_ma(10, -1))

        return was_bullish and cross

    def _is_cross_up(self) -> bool:
        """
        空头排列后金叉：
        - 前一天处于空头排列
        - MA10 上穿 MA20（前一天 MA10<MA20，今天 MA10>MA20）
        """
        if len(self.ma_history[10]) < 2 or len(self.ma_history[20]) < 2:
            return False

        was_bearish = self.bearish_history[-2]

        cross = (self._get_ma(10, -2) < self._get_ma(20, -2) and
                 self._get_ma(10, -1) > self._get_ma(20, -1))

        return was_bearish and cross

    def _is_struggle(self) -> bool:
        """判断均线纠缠"""
        if len(self.ma_history[30]) < 1:
            return False

        diff_10_20 = abs(self._get_ma(10) - self._get_ma(20)) / self._get_ma(20)
        diff_20_30 = abs(self._get_ma(20) - self._get_ma(30)) / self._get_ma(30)

        return (diff_10_20 < self.struggle_threshold_10_20 or
                diff_20_30 < self.struggle_threshold_20_30)

    # ==================== 交易执行 ====================

    def _set_buy_target(self, bar: BarData, reason: str) -> None:
        """计算并设置买入目标仓位"""
        cash = self.get_cash_available()
        buy_value = cash * self.cash_ratio

        order_price = bar.close_price * (1 + self.price_add)
        volume = round_to(buy_value / order_price, 100)

        if volume >= 100:
            self.set_target(bar.vt_symbol, volume)
            self.write_log(f"{reason} 买入 {volume}股 @ {order_price:.2f}")
