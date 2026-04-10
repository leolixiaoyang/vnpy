"""
小市值杠铃策略（基于聚宽版本思路移植）
====================================
策略逻辑：
- 基本面过滤后按流通市值从小到大选股
- 按固定周期调仓，支持空仓月份
- 持仓股触发固定止损后卖出
- 股票+黄金ETF杠铃配置控制回撤

说明：
该策略依赖 signal_df 中提供基础过滤字段（如 pe/pb/roe 等）以及
技术过滤字段（如 vol20/ma10/ma20/recent_drop）。若字段缺失，策略会自动降级处理。
"""

from collections import defaultdict

import polars as pl

from vnpy.trader.constant import Direction
from vnpy.trader.object import BarData, TradeData
from vnpy.trader.utility import round_to

from vnpy.alpha import AlphaStrategy


class SmallCapBarbellStrategy(AlphaStrategy):
    """小市值杠铃策略"""

    # 组合参数
    stock_num: int = 20
    query_pool_num: int = 400
    small_cap_pool_num: int = 100

    # 调仓参数
    rebalance_interval: int = 7
    empty_months: list[int] = [1, 4]
    day_count: int = 0

    # 资产配置参数
    enable_barbell: bool = True
    stock_ratio: float = 0.5
    gold_ratio: float = 0.5
    gold_etf: str = "518880.SSE"

    # 风控参数
    min_listing_days: int = 365
    stop_loss_rate: float = 0.08
    min_trade_volume: int = 100
    price_add: float = 0.05

    # 选股阈值（可按需调参）
    pe_max: float = 50
    roe_min: float = 0.05
    vol20_max: float = 0.07
    trend_buffer_up: float = 0.98
    trend_buffer_ma: float = 0.97

    def on_init(self) -> None:
        """策略初始化"""
        self.cost_data: dict[str, float] = defaultdict(float)

        # 兼容用户通过 setting 覆盖空仓月份为字符串等情况
        self.empty_months = [int(m) for m in self.empty_months]

        self.write_log("小市值杠铃策略初始化")
        self.write_log(f"持股数: {self.stock_num}, 调仓周期: {self.rebalance_interval}天")

    def on_trade(self, trade: TradeData) -> None:
        """成交回调"""
        vt_symbol: str = trade.vt_symbol

        if trade.direction == Direction.LONG:
            # 简化处理：同一标的多次买入时，使用最近一次成交价作为止损参考成本
            self.cost_data[vt_symbol] = trade.price
        else:
            if self.get_pos(vt_symbol) <= 0:
                self.cost_data.pop(vt_symbol, None)

    def on_bars(self, bars: dict[str, BarData]) -> None:
        """K线回调"""
        if not bars:
            return

        self._check_stop_loss(bars)

        if self._is_empty_window():
            self._clear_stock_position()
            self.day_count = 0
            self.execute_trading(bars, price_add=self.price_add)
            return

        if self.day_count % self.rebalance_interval != 0:
            self.day_count += 1
            self.execute_trading(bars, price_add=self.price_add)
            return

        target_list: list[str] = self._select_stocks(bars)
        self._adjust_position(bars, target_list)

        self.day_count = 1
        self.execute_trading(bars, price_add=self.price_add)

    def _select_stocks(self, bars: dict[str, BarData]) -> list[str]:
        """按信号数据选股"""
        signal_df: pl.DataFrame = self.get_signal()
        if signal_df.is_empty():
            return []

        required_columns: set[str] = {"vt_symbol", "market_cap"}
        if not required_columns.issubset(set(signal_df.columns)):
            self.write_log("signal_df 缺少 vt_symbol/market_cap，无法执行选股")
            return []

        df: pl.DataFrame = signal_df

        # 可选字段过滤（缺失时降级跳过）
        if "pb_ratio" in df.columns:
            df = df.filter(pl.col("pb_ratio") > 0)
        if "pe_ratio" in df.columns:
            df = df.filter((pl.col("pe_ratio") > 0) & (pl.col("pe_ratio") < self.pe_max))
        if "roe" in df.columns:
            df = df.filter(pl.col("roe") > self.roe_min)
        if "net_profit" in df.columns:
            df = df.filter(pl.col("net_profit") > 0)
        if "net_operate_cash_flow" in df.columns:
            df = df.filter(pl.col("net_operate_cash_flow") > 0)
        if "list_days" in df.columns:
            df = df.filter(pl.col("list_days") >= self.min_listing_days)
        if "is_paused" in df.columns:
            df = df.filter(pl.col("is_paused") == False)
        if "is_st" in df.columns:
            df = df.filter(pl.col("is_st") == False)
        if "recent_drop" in df.columns:
            df = df.filter(pl.col("recent_drop") == False)

        if df.is_empty():
            return []

        # 主板过滤：排除创业板/科创板/北交所风格代码
        df = df.filter(~pl.col("vt_symbol").str.contains(r"^(300|301|688|689|8|4)"))
        if df.is_empty():
            return []

        # 先取小市值候选池
        df = df.sort("market_cap").head(self.query_pool_num)
        df = df.sort("market_cap").head(self.small_cap_pool_num)

        # 技术过滤：若提供对应字段则启用
        if "close" in df.columns:
            df = df.filter(pl.col("close") >= 2)
        if "vol20" in df.columns:
            df = df.filter(pl.col("vol20") < self.vol20_max)
        if {"close", "ma10"}.issubset(set(df.columns)):
            df = df.filter(pl.col("close") >= pl.col("ma10") * self.trend_buffer_up)
        if {"ma10", "ma20"}.issubset(set(df.columns)):
            df = df.filter(pl.col("ma10") >= pl.col("ma20") * self.trend_buffer_ma)

        if df.is_empty():
            return []

        # 仅保留当前可交易行情里有 bar 的标的
        tradable_set: set[str] = set(bars.keys())
        df = df.filter(pl.col("vt_symbol").is_in(list(tradable_set)))

        if df.is_empty():
            return []

        # 排序逻辑：优先低波动、低市值
        sort_cols: list[str] = []
        if "vol20" in df.columns:
            sort_cols.append("vol20")
        sort_cols.append("market_cap")

        df = df.sort(sort_cols)

        return list(df["vt_symbol"][:self.stock_num])

    def _adjust_position(self, bars: dict[str, BarData], target_list: list[str]) -> None:
        """调仓：卖出现有非目标持仓，买入目标持仓，按杠铃分配仓位"""
        hold_symbols: list[str] = [vt for vt, pos in self.pos_data.items() if pos > 0]
        stock_holdings: list[str] = [s for s in hold_symbols if s != self.gold_etf]

        # 先卖出不在目标池中的股票
        for vt_symbol in stock_holdings:
            if vt_symbol not in target_list:
                self.set_target(vt_symbol, 0)

        if not target_list:
            return

        portfolio_value: float = self.get_portfolio_value()

        if self.enable_barbell:
            stock_value: float = portfolio_value * self.stock_ratio / len(target_list)
            gold_value: float = portfolio_value * self.gold_ratio

            if self.gold_etf in bars:
                gold_price = bars[self.gold_etf].close_price
                if gold_price > 0:
                    gold_volume = round_to(gold_value / gold_price, self.min_trade_volume)
                    self.set_target(self.gold_etf, max(gold_volume, 0))
        else:
            stock_value = portfolio_value / len(target_list)

        for vt_symbol in target_list:
            bar: BarData | None = bars.get(vt_symbol)
            if not bar or bar.close_price <= 0:
                continue

            target_volume: float = round_to(stock_value / bar.close_price, self.min_trade_volume)
            if target_volume >= self.min_trade_volume:
                self.set_target(vt_symbol, target_volume)

    def _clear_stock_position(self) -> None:
        """清空股票仓位（保留黄金ETF）"""
        for vt_symbol, pos in list(self.pos_data.items()):
            if pos <= 0:
                continue
            if vt_symbol == self.gold_etf:
                continue
            self.set_target(vt_symbol, 0)

    def _check_stop_loss(self, bars: dict[str, BarData]) -> None:
        """固定止损：价格较成本跌幅超过阈值即清仓"""
        for vt_symbol, pos in list(self.pos_data.items()):
            if pos <= 0:
                continue
            if vt_symbol == self.gold_etf:
                continue

            bar: BarData | None = bars.get(vt_symbol)
            if not bar:
                continue

            cost_price: float = self.cost_data.get(vt_symbol, 0)
            if cost_price <= 0:
                continue

            loss_rate: float = (cost_price - bar.close_price) / cost_price
            if loss_rate >= self.stop_loss_rate:
                self.set_target(vt_symbol, 0)
                self.write_log(f"止损卖出: {vt_symbol}, 跌幅 {loss_rate:.2%}")

    def _is_empty_window(self) -> bool:
        """判断当前月份是否为空仓窗口"""
        if not self.strategy_engine.datetime:
            return False
        return self.strategy_engine.datetime.month in self.empty_months
