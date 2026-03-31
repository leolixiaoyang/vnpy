"""
昨日涨停今日买入策略
========================
策略逻辑：
1. T 日筛选涨停股票（根据板块区分涨停幅度）
2. T+1 日开盘买入（按市值从大到小选前 10 只）
3. 动态止盈止损卖出

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


class LimitUpStrategy(AlphaStrategy):
    """昨日涨停今日买入策略"""

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
        self.holding_days: dict[str, int] = defaultdict(int)      # 持有天数
        self.buy_price: dict[str, float] = {}                      # 买入价格
        self.high_price: dict[str, float] = {}                     # 持仓期间最高价
        
        # 股票池
        self.limit_up_symbols: list[str] = []                      # 昨日涨停股票列表
        self.stock_info: dict[str, dict] = {}                      # 股票信息（市值等）
        
        # 交易记录
        self.trade_count: int = 0
        self.win_count: int = 0
        self.loss_count: int = 0
        
        self.write_log("策略初始化完成")
        self.write_log(f"最大持仓数：{self.max_positions}")
        self.write_log(f"止损：{self.stop_loss_rate*100}%, 止盈：{self.take_profit_rate*100}%")

    def on_trade(self, trade: TradeData) -> None:
        """成交回调"""
        vt_symbol = trade.vt_symbol
        
        # 开仓记录
        if trade.direction == Direction.LONG:
            self.buy_price[vt_symbol] = trade.price
            self.high_price[vt_symbol] = trade.price
            self.holding_days[vt_symbol] = 0
            self.trade_count += 1
            self.write_log(f"开仓：{vt_symbol}, 价格：{trade.price}, 数量：{trade.volume}")
        
        # 平仓记录
        elif trade.direction == Direction.SHORT:
            if vt_symbol in self.buy_price:
                buy_price = self.buy_price[vt_symbol]
                profit_rate = (trade.price - buy_price) / buy_price
                
                if profit_rate > 0:
                    self.win_count += 1
                else:
                    self.loss_count += 1
                
                self.write_log(
                    f"平仓：{vt_symbol}, 买入：{buy_price}, 卖出：{trade.price}, "
                    f"盈亏：{profit_rate*100:.2f}%"
                )
                
                # 清理记录
                self.buy_price.pop(vt_symbol, None)
                self.high_price.pop(vt_symbol, None)
                self.holding_days.pop(vt_symbol, None)

    def on_bars(self, bars: dict[str, BarData]) -> None:
        """K 线回调（每日调用）"""
        if not bars:
            return
        
        # ========== 1. 更新持仓信息 ==========
        self._update_holdings(bars)
        
        # ========== 2. 检查止盈止损 ==========
        sell_symbols = self._check_exit_conditions(bars)
        
        # ========== 3. 筛选昨日涨停股票 ==========
        buy_symbols = self._select_limit_up_stocks(bars)
        
        # ========== 4. 执行交易 ==========
        self._execute_trading(bars, sell_symbols, buy_symbols)

    def _update_holdings(self, bars: dict[str, BarData]) -> None:
        """更新持仓信息（持有天数、最高价）"""
        pos_symbols = [vt for vt, pos in self.pos_data.items() if pos > 0]
        
        for vt_symbol in pos_symbols:
            # 更新持有天数
            self.holding_days[vt_symbol] += 1
            
            # 更新最高价
            if vt_symbol in bars:
                bar = bars[vt_symbol]
                current_high = self.high_price.get(vt_symbol, 0)
                self.high_price[vt_symbol] = max(current_high, bar.high_price)

    def _check_exit_conditions(self, bars: dict[str, BarData]) -> list[str]:
        """检查止盈止损条件，返回需要卖出的股票列表"""
        sell_symbols = []
        pos_symbols = [vt for vt, pos in self.pos_data.items() if pos > 0]
        
        for vt_symbol in pos_symbols:
            if vt_symbol not in bars:
                continue
            
            bar = bars[vt_symbol]
            buy_price = self.buy_price.get(vt_symbol, 0)
            high_price = self.high_price.get(vt_symbol, 0)
            current_price = bar.close_price
            
            if buy_price <= 0:
                continue
            
            # 计算收益率
            profit_rate = (current_price - buy_price) / buy_price
            
            # 计算回撤（从最高价回撤）
            drawdown = (high_price - current_price) / high_price if high_price > 0 else 0
            
            # 持有天数
            hold_days = self.holding_days.get(vt_symbol, 0)
            
            # ========== 止损条件 ==========
            if profit_rate <= -self.stop_loss_rate:
                sell_symbols.append(vt_symbol)
                self.write_log(f"止损：{vt_symbol}, 盈亏：{profit_rate*100:.2f}%")
                continue
            
            # ========== 止盈条件 ==========
            # 条件 1：达到止盈线
            if profit_rate >= self.take_profit_rate:
                sell_symbols.append(vt_symbol)
                self.write_log(f"止盈：{vt_symbol}, 盈亏：{profit_rate*100:.2f}%")
                continue
            
            # 条件 2：盈利后回撤超过阈值
            if profit_rate > 0 and drawdown >= self.trailing_stop_rate:
                sell_symbols.append(vt_symbol)
                self.write_log(f"回撤止盈：{vt_symbol}, 最高盈利：{(high_price-buy_price)/buy_price*100:.2f}%, 当前：{profit_rate*100:.2f}%")
                continue
            
            # 条件 3：超过最大持有天数
            if hold_days >= self.max_hold_days:
                sell_symbols.append(vt_symbol)
                self.write_log(f"超期卖出：{vt_symbol}, 持有：{hold_days}天，盈亏：{profit_rate*100:.2f}%")
                continue
        
        return sell_symbols

    def _select_limit_up_stocks(self, bars: dict[str, BarData]) -> list[str]:
        """筛选昨日涨停股票（按市值从大到小选前 N 只）"""
        # 获取信号数据（由外部模型或数据提供）
        signal_df = self.get_signal()
        
        if signal_df is None or signal_df.is_empty():
            return []
        
        # 筛选昨日涨停的股票
        limit_up_df = signal_df.filter(pl.col("is_limit_up") == True)
        
        if limit_up_df.is_empty():
            return []
        
        # 按市值从大到小排序
        limit_up_df = limit_up_df.sort("market_cap", descending=True)
        
        # 取前 N 只
        top_n = limit_up_df.head(self.max_positions)
        
        buy_symbols = list(top_n["vt_symbol"])
        
        if buy_symbols:
            self.write_log(f"昨日涨停股票数：{len(limit_up_df)}, 候选买入：{len(buy_symbols)}")
        
        return buy_symbols

    def _execute_trading(
        self,
        bars: dict[str, BarData],
        sell_symbols: list[str],
        buy_symbols: list[str]
    ) -> None:
        """执行交易"""
        # ========== 1. 卖出 ==========
        cash = self.get_cash_available()
        
        for vt_symbol in sell_symbols:
            if vt_symbol not in bars:
                continue
            
            bar = bars[vt_symbol]
            sell_price = bar.open_price  # 开盘价卖出
            
            # 获取持仓数量
            sell_volume = self.get_pos(vt_symbol)
            
            if sell_volume <= 0:
                continue
            
            # 设置目标仓位为 0
            self.set_target(vt_symbol, target=0)
            
            # 更新现金（估算）
            turnover = sell_price * sell_volume
            cost = max(turnover * 0.0015, 5)  # 卖出手续费
            cash += turnover - cost
        
        # ========== 2. 买入 ==========
        if not buy_symbols:
            return
        
        # 计算每只股票的买入金额（等权重）
        valid_buy_symbols = [s for s in buy_symbols if s in bars]
        
        if not valid_buy_symbols:
            return
        
        # 过滤已持仓的股票
        pos_symbols = [vt for vt, pos in self.pos_data.items() if pos > 0]
        new_buy_symbols = [s for s in valid_buy_symbols if s not in pos_symbols]
        
        if not new_buy_symbols:
            return
        
        # 计算可用现金和买入金额
        available_cash = cash * 0.95  # 保留 5% 现金
        buy_value = available_cash / len(new_buy_symbols)
        
        for vt_symbol in new_buy_symbols:
            bar = bars[vt_symbol]
            buy_price = bar.open_price  # 开盘价买入
            
            if buy_price <= 0:
                continue
            
            # 计算买入数量（手）
            buy_volume = round_to(buy_value / buy_price, self.min_volume)
            
            if buy_volume < self.min_volume:
                continue
            
            # 设置目标仓位
            self.set_target(vt_symbol, buy_volume)
            
            self.write_log(
                f"买入：{vt_symbol}, 价格：{buy_price}, 数量：{buy_volume}, "
                f"金额：{buy_price * buy_volume:.2f}"
            )

    def on_daily(self) -> None:
        """每日收盘后回调（可选）"""
        # 统计信息
        if self.trade_count > 0:
            win_rate = self.win_count / self.trade_count * 100
            self.write_log(f"交易统计：总交易={self.trade_count}, 胜率={win_rate:.2f}%")
