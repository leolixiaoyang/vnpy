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

交易执行：
- T 日收盘后判断信号
- T+1 日开盘价执行，叠加滑点
"""

from vnpy.trader.object import BarData, TradeData
from vnpy.trader.utility import round_to
from vnpy.trader.constant import Direction

import numpy as np
import talib

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
    use_next_day: bool = True             # T+1 交易模式
    slippage: float = 0.001               # 滑点比例，默认 0.1%
    stop_loss_rate: float = 0.08          # 止损比例，默认 8%
    adx_period: int = 14                  # ADX 计算周期
    adx_threshold: float = 20.0           # ADX 趋势强度阈值

    def on_init(self) -> None:
        """策略初始化"""
        if self.ma_periods is None:
            self.ma_periods = [5, 10, 20, 30]

        self.ma_history: dict[int, list[float]] = {p: [] for p in self.ma_periods}
        self.bullish_history: list[bool] = []
        self.bearish_history: list[bool] = []
        self.pending_order: dict | None = None  # T 日信号，T+1 日执行
        self.buy_price: float = 0.0             # 持仓入场价（止损基准）
        self.adx_value: float = 0.0             # 当前 ADX 值

        self.write_log("多均线择时策略初始化")
        self.write_log(f"均线周期: {self.ma_periods}")
        self.write_log(f"T+1 模式: {self.use_next_day}, 滑点: {self.slippage*100:.2f}%")
        self.write_log(f"止损: {self.stop_loss_rate*100:.2f}%, ADX({self.adx_period}) 阈值: {self.adx_threshold}")

    def on_trade(self, trade: TradeData) -> None:
        """成交回调 -- 记录入场价用于止损"""
        pos: float = self.get_pos(trade.vt_symbol)
        self.write_log(f"成交: {trade.vt_symbol}, 方向={trade.direction.value}, 价格={trade.price}, 数量={trade.volume}, 持仓={pos}")

        if trade.direction == Direction.LONG:
            self.buy_price = trade.price
        elif pos == 0:
            self.buy_price = 0.0

    def on_bars(self, bars: dict[str, BarData]) -> None:
        """K 线回调"""
        if not bars:
            return

        vt_symbol = self.stock or list(bars.keys())[0]
        bar: BarData | None = bars.get(vt_symbol)
        if not bar:
            return

        # 1. 执行前一日缓存的订单（T+1 模式）
        if self.use_next_day and self.pending_order:
            self._execute_pending_order(bar)
            self.execute_trading(bars, price_add=self.price_add)
            # 订单已发送，等待次日撮合后再判断新信号
            return

        # 2. 更新均线（用今天的收盘价计算）
        self._update_ma_values(vt_symbol)

        # 3. 计算 ADX（用于趋势过滤）
        self._update_adx(vt_symbol)

        # 4. 判断今天信号（写入 pending_order，次日执行）
        if not self.use_next_day:
            self._execute_signals(bars)
            return

        # T+1 模式：缓存信号到次日
        if len(self.bullish_history) < 2:
            self.bullish_history.append(self._is_bullish())
            self.bearish_history.append(self._is_bearish())
            return
        if any(len(self.ma_history[p]) < 3 for p in [5, 10, 20]):
            return

        is_bull = self._is_bullish()
        is_bear = self._is_bearish()
        self.bullish_history.append(is_bull)
        self.bearish_history.append(is_bear)

        current_pos: float = self.get_pos(vt_symbol)

        # ========== 止损检查（最高优先级，覆盖现有 pending_order） ==========
        if self._check_stop_loss(current_pos, bar):
            return

        # 已有待执行订单，不覆盖
        if self.pending_order:
            return

        # ---------- 多头后死叉 → 卖出 ----------
        if current_pos > 0 and self._is_cross_down():
            self._set_pending_sell_order(bar, reason="死叉")

        # ---------- 空头后金叉 → 买入（ADX 过滤） ----------
        elif current_pos == 0 and self._is_cross_up():
            if not self._adx_allow_buy():
                self.write_log(f"[过滤] 金叉信号被 ADX 过滤 (ADX={self.adx_value:.1f})")
                return
            self._set_pending_buy_order(bar, reason="金叉")

        # ---------- 多头排列 → 买入（ADX 过滤） ----------
        elif current_pos == 0 and is_bull:
            if not self._adx_allow_buy():
                self.write_log(f"[过滤] 多头排列信号被 ADX 过滤 (ADX={self.adx_value:.1f})")
                return
            self._set_pending_buy_order(bar, reason="多头排列")

        # ---------- 空头排列 → 卖出 ----------
        elif current_pos > 0 and is_bear:
            self._set_pending_sell_order(bar, reason="空头排列")

    # ==================== 信号判断 ====================

    def _is_bullish(self) -> bool:
        required = [5, 10, 20, 30]
        for p in required:
            if len(self.ma_history[p]) < 1:
                return False
        return (self._get_ma(5) > self._get_ma(10) >
                self._get_ma(20) > self._get_ma(30))

    def _is_bearish(self) -> bool:
        required = [5, 10, 20]
        for p in required:
            if len(self.ma_history[p]) < 1:
                return False
        return self._get_ma(5) < self._get_ma(10) < self._get_ma(20)

    def _is_cross_down(self) -> bool:
        if len(self.ma_history[5]) < 2 or len(self.ma_history[10]) < 2:
            return False
        was_bullish = self.bullish_history[-2]
        cross = (self._get_ma(5, -2) > self._get_ma(10, -2) and
                 self._get_ma(5, -1) < self._get_ma(10, -1))
        return was_bullish and cross

    def _is_cross_up(self) -> bool:
        if len(self.ma_history[10]) < 2 or len(self.ma_history[20]) < 2:
            return False
        was_bearish = self.bearish_history[-2]
        cross = (self._get_ma(10, -2) < self._get_ma(20, -2) and
                 self._get_ma(10, -1) > self._get_ma(20, -1))
        return was_bearish and cross

    def _is_struggle(self) -> bool:
        """判断均线纠缠（V0.2 已弃用，保留以兼容旧配置）"""
        if len(self.ma_history[30]) < 1:
            return False
        diff_10_20 = abs(self._get_ma(10) - self._get_ma(20)) / self._get_ma(20)
        diff_20_30 = abs(self._get_ma(20) - self._get_ma(30)) / self._get_ma(30)
        return (diff_10_20 < self.struggle_threshold_10_20 or
                diff_20_30 < self.struggle_threshold_20_30)

    def _update_adx(self, vt_symbol: str) -> None:
        """计算当前 ADX 值"""
        n = self.adx_period
        history = self.get_history_bars(vt_symbol, 2 * n)
        if len(history) < 2 * n - 1:
            self.adx_value = 0.0
            return

        high = np.array([b.high_price for b in history])
        low = np.array([b.low_price for b in history])
        close = np.array([b.close_price for b in history])

        adx_array = talib.ADX(high, low, close, n)
        self.adx_value = float(adx_array[-1])

    def _check_stop_loss(self, current_pos: float, bar: BarData) -> bool:
        """止损检查。触发时设置 pending sell 并返回 True。

        优先级最高：即使已有 pending buy 也会被覆盖。
        """
        if current_pos > 0 and self.buy_price > 0:
            stop_price = self.buy_price * (1 - self.stop_loss_rate)
            if bar.close_price <= stop_price:
                self._set_pending_sell_order(bar, reason="止损")
                return True
        return False

    def _adx_allow_buy(self) -> bool:
        """ADX 趋势过滤：低于阈值时不允许买入"""
        if self.adx_value == 0.0:
            return True  # 数据不足时放行
        return self.adx_value >= self.adx_threshold

    # ==================== 均线计算 ====================

    def _update_ma_values(self, vt_symbol: str) -> None:
        history = self.get_history_bars(vt_symbol, max(self.ma_periods))
        if len(history) >= max(self.ma_periods):
            closes = [b.close_price for b in history]
            for period in self.ma_periods:
                ma = sum(closes[-period:]) / period
                self.ma_history[period].append(ma)

    def _get_ma(self, period: int, offset: int = -1) -> float:
        return self.ma_history[period][offset]

    # ==================== T+1 执行 ====================

    def _set_pending_buy_order(self, bar: BarData, reason: str) -> None:
        """缓存买入信号，次日开盘执行"""
        self.pending_order = {
            "vt_symbol": bar.vt_symbol,
            "action": "buy",
            "reason": reason,
            "signal_date": self.strategy_engine.datetime.strftime("%Y-%m-%d"),
        }
        self.write_log(f"[信号] {reason} 买入 @ {self.pending_order['signal_date']}")

    def _set_pending_sell_order(self, bar: BarData, reason: str) -> None:
        """缓存卖出信号，次日开盘执行"""
        self.pending_order = {
            "vt_symbol": bar.vt_symbol,
            "action": "sell",
            "reason": reason,
            "signal_date": self.strategy_engine.datetime.strftime("%Y-%m-%d"),
        }
        self.write_log(f"[信号] {reason} 清仓 @ {self.pending_order['signal_date']}")

    def _execute_pending_order(self, bar: BarData) -> None:
        """执行待处理订单（T+1 日开盘执行 T 日信号）"""
        order = self.pending_order
        open_price = bar.open_price

        if order["action"] == "buy":
            exec_price = open_price * (1 + self.slippage)
            cash = self.get_cash_available()
            buy_value = cash * self.cash_ratio
            volume = round_to(buy_value / exec_price, 100)
            if volume >= 100:
                self.set_target(bar.vt_symbol, volume)
                self.write_log(
                    f"[成交] {order['reason']} 买入 {volume}股 "
                    f"@ 开盘{open_price:.2f} + 滑点{self.slippage*100:.2f}% → {exec_price:.2f}"
                )
            else:
                self.write_log(f"[跳过] 买入量 {volume}股 < 100，不执行")
        else:
            self.set_target(bar.vt_symbol, 0)
            self.write_log(
                f"[成交] {order['reason']} 清仓 "
                f"@ 开盘{open_price:.2f} - 滑点{self.slippage*100:.2f}%"
            )

        self.pending_order = None

    # ==================== 非 T+1 模式（旧逻辑） ====================

    def _execute_signals(self, bars: dict[str, BarData]) -> None:
        """非 T+1 模式：当天信号当天执行"""
        vt_symbol = self.stock or list(bars.keys())[0]
        bar: BarData | None = bars.get(vt_symbol)
        if not bar:
            return

        if any(len(self.ma_history[p]) < 3 for p in [5, 10, 20]):
            return

        if len(self.bullish_history) < 2:
            self.bullish_history.append(self._is_bullish())
            self.bearish_history.append(self._is_bearish())
            self.execute_trading(bars, price_add=self.price_add)
            return

        is_bull = self._is_bullish()
        is_bear = self._is_bearish()
        self.bullish_history.append(is_bull)
        self.bearish_history.append(is_bear)

        current_pos: float = self.get_pos(vt_symbol)

        # 止损检查（非 T+1 模式直接执行）
        if current_pos > 0 and self.buy_price > 0:
            stop_price = self.buy_price * (1 - self.stop_loss_rate)
            if bar.close_price <= stop_price:
                self.set_target(vt_symbol, 0)
                self.write_log(f"止损 清仓: 入场={self.buy_price:.2f}, 收盘={bar.close_price:.2f}")
                self.execute_trading(bars, price_add=self.price_add)
                return

        if current_pos > 0 and self._is_cross_down():
            self.set_target(vt_symbol, 0)
            self.write_log("死叉 清仓")
        elif current_pos == 0 and self._is_cross_up():
            if not self._adx_allow_buy():
                return
            self._set_buy_target(bar, reason="金叉")
        elif current_pos == 0 and is_bull:
            if not self._adx_allow_buy():
                return
            self._set_buy_target(bar, reason="多头排列")
        elif current_pos > 0 and is_bear:
            self.set_target(vt_symbol, 0)
            self.write_log("空头排列 清仓")

        self.execute_trading(bars, price_add=self.price_add)

    def _set_buy_target(self, bar: BarData, reason: str) -> None:
        cash = self.get_cash_available()
        buy_value = cash * self.cash_ratio
        order_price = bar.close_price * (1 + self.price_add)
        volume = round_to(buy_value / order_price, 100)
        if volume >= 100:
            self.set_target(bar.vt_symbol, volume)
            self.write_log(f"{reason} 买入 {volume}股 @ {order_price:.2f}")
