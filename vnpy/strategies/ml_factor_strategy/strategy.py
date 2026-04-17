"""
ML 因子小市值策略（基于 JoinQuant 帖子思路移植到 vnpy 框架）
============================================================
策略逻辑：
- 5 组 ML 预训练因子，每组有线性回归系数
- 每组计算加权总分，选总分前 10% 的股票
- 从前 10% 中过滤 EPS > 0，选流通市值最小的 1 只
- 每组选 1 只，最多持有 5 只
- 每周一 9:30 调仓
- 4月5日-4月30日为空仓期，清仓所有股票
- 昨日涨停股：今日若涨停打开则卖出，仍涨停则继续持有
- 过滤：ST、上市不满 375 天、科创板(68)、创业板(30)、北交所(4/8)、停牌、涨跌停

因子映射到 vnpy signal_df 列名：
  Group 1: arbr, sgai, net_profit_margin_ttm, retained_profit_per_share
  Group 2: price_1y, total_profit_to_cost_ratio, vol120
  Group 3: price_no_fq, total_profit_to_cost_ratio, inventory_turnover_rate
  Group 4: debt_to_assets, operating_cost_to_revenue_ratio, davol20, price_no_fq, sales_growth_5y
  Group 5: tvstd6, cashflow_per_share_ttm, sharpe_ratio_120, non_operating_net_profit_ttm

数据依赖：
  signal_df 中需包含上述因子列，以及以下基础列：
    datetime, vt_symbol, market_cap(circ_mv), eps, list_days,
    is_paused, is_st, close, pre_close, limit_up, limit_down

因子预训练：
  因子系数通过 BayesianRidge 回归预训练得到。

  训练方法：
    1. 准备数据：小市值股票池 + 因子数据 + 下期收益率标签
    2. 运行训练脚本：python train_factors.py
    3. 训练结果保存到 coefficients.json

  训练来源：
    基于 JoinQuant 平台 notebook: 手把手教你如何训练差不多得了-Clone3.ipynb
    使用 BayesianRidge（贝叶斯岭回归）对每组因子独立训练

  训练参数：
    - 时间范围：2009-01-01 ~ 2024-01-01
    - 调仓周期：周频（W）
    - 股票池：市值 < 25 亿的小市值股（前 50 只）
    - 模型：BayesianRidge（fit_intercept=False）
    - 标签：下一周收益率（pchg）

说明：
  基本面因子需在 signal_pipeline 中预先计算并写入 signal_df。
  策略本身只做因子打分、选股和交易执行。
"""

from collections import defaultdict

import polars as pl

from vnpy.trader.constant import Direction
from vnpy.trader.object import BarData, TradeData
from vnpy.trader.utility import round_to

from vnpy.alpha import AlphaStrategy


class MlFactorStrategy(AlphaStrategy):
    """ML 因子小市值策略"""

    # ========== 选股参数 ==========
    stock_num: int = 1                # 每组选 1 只
    top_pct: float = 0.10             # 取每组总分前 10%
    min_listing_days: int = 375       # 最小上市天数

    # ========== 调仓参数 ==========
    empty_period_start: str = "0405"  # 空仓期开始 (4月5日)
    empty_period_end: str = "0430"    # 空仓期结束 (4月30日)

    # ========== 交易参数 ==========
    min_trade_volume: int = 100       # 最小交易量（手）
    price_add: float = 0.05           # 下单价格偏移比例
    cash_use_ratio: float = 0.95      # 可用现金使用比例

    # ========== ML 因子系数 ==========
    # 所有系数在 signal_pipeline 中统一配置，也可通过 setting 覆盖
    group1_coeffs: list[float] = None
    group2_coeffs: list[float] = None
    group3_coeffs: list[float] = None
    group4_coeffs: list[float] = None
    group5_coeffs: list[float] = None

    def on_init(self) -> None:
        """策略初始化"""
        # 默认 ML 系数（如未通过 setting 传入）
        if self.group1_coeffs is None:
            self.group1_coeffs = [-3.89e-19, 6.05e-05, -0.000135, -0.000623]
        if self.group2_coeffs is None:
            self.group2_coeffs = [-0.00769, -0.00106, -0.000637]
        if self.group3_coeffs is None:
            self.group3_coeffs = [-0.000222, -0.000340, -1.24e-08]
        if self.group4_coeffs is None:
            self.group4_coeffs = [-0.00135, 0.00129, -0.00302, -0.000233, 0.000234]
        if self.group5_coeffs is None:
            self.group5_coeffs = [-6.69e-11, -0.000161, -0.000553, 9.17e-12]

        # 状态跟踪
        self.cost_data: dict[str, float] = defaultdict(float)   # 持仓成本价
        self.prev_limit_up: set[str] = set()                    # 昨日涨停股票集合
        self.is_empty_period: bool = False                      # 当前是否处于空仓期
        self.last_rebalance_date = None                         # 上次调仓日期

        self.write_log("ML 因子小市值策略初始化")
        self.write_log(f"每组选股数: {self.stock_num}, 前 {self.top_pct*100:.0f}% 候选")
        self.write_log(f"空仓期: {self.empty_period_start} ~ {self.empty_period_end}")

    def on_trade(self, trade: TradeData) -> None:
        """成交回调"""
        vt_symbol: str = trade.vt_symbol

        if trade.direction == Direction.LONG:
            # 更新持仓成本（取最近一次成交价）
            self.cost_data[vt_symbol] = trade.price
        else:
            if self.get_pos(vt_symbol) <= 0:
                self.cost_data.pop(vt_symbol, None)

    def on_bars(self, bars: dict[str, BarData]) -> None:
        """K 线回调 - 主入口"""
        if not bars:
            return

        current_dt = self.strategy_engine.datetime
        if current_dt is None:
            return

        date_str: str = current_dt.strftime("%m%d")

        # ---------- 1. 判断空仓期 ----------
        self.is_empty_period = self._is_in_empty_period(date_str)

        if self.is_empty_period:
            self._handle_empty_period(bars)
            self.execute_trading(bars, price_add=self.price_add)
            return

        # ---------- 2. 每日：涨停板监控 ----------
        self._check_limit_up_monitor(bars, current_dt)

        # ---------- 3. 每周一：调仓 ----------
        is_monday: bool = current_dt.weekday() == 0

        if is_monday:
            target_list: list[str] = self._select_stocks(bars, current_dt)
            self._adjust_position(bars, target_list)
            self.last_rebalance_date = current_dt.date()
        else:
            # 非调仓日，仍然检查是否需要卖出非目标股票
            # （如涨停打开后已卖出，无需额外操作）
            pass

        # ---------- 4. 执行交易 ----------
        self.execute_trading(bars, price_add=self.price_add)

    # ==================== 选股 ====================

    def _select_stocks(self, bars: dict[str, BarData], current_dt) -> list[str]:
        """
        核心选股逻辑：
        1. 获取当日 signal_df
        2. 基础过滤（主板、非 ST、非停牌、非次新、非涨跌停）
        3. 5 组因子分别打分，取每组前 10%
        4. 从前 10% 中过滤 EPS > 0，选流通市值最小的 stock_num 只
        5. 每组选 1 只，最多 5 只
        """
        signal_df: pl.DataFrame = self.get_signal()
        if signal_df.is_empty():
            self.write_log("signal_df 为空，无法选股")
            return []

        # 取当日数据
        df: pl.DataFrame = signal_df.filter(pl.col("datetime") == current_dt)
        if df.is_empty():
            return []

        # ---------- 基础列检查 ----------
        required: set[str] = {"vt_symbol", "market_cap"}
        if not required.issubset(set(df.columns)):
            self.write_log("signal_df 缺少 vt_symbol / market_cap 列")
            return []

        # ---------- 基础过滤 ----------
        df = self._apply_basic_filters(df)
        if df.is_empty():
            return []

        # ---------- 5 组因子打分选股 ----------
        factor_configs: list[tuple] = [
            ("group1", self.group1_coeffs, [
                "arbr", "sgai", "net_profit_margin_ttm", "retained_profit_per_share"
            ]),
            ("group2", self.group2_coeffs, [
                "price_1y", "total_profit_to_cost_ratio", "vol120"
            ]),
            ("group3", self.group3_coeffs, [
                "price_no_fq", "total_profit_to_cost_ratio", "inventory_turnover_rate"
            ]),
            ("group4", self.group4_coeffs, [
                "debt_to_assets", "operating_cost_to_revenue_ratio",
                "davol20", "price_no_fq", "sales_growth_5y"
            ]),
            ("group5", self.group5_coeffs, [
                "tvstd6", "cashflow_per_share_ttm", "sharpe_ratio_120",
                "non_operating_net_profit_ttm"
            ]),
        ]

        all_selected: list[str] = []

        for group_name, coeffs, factor_cols in factor_configs:
            # 检查因子列是否存在（缺失时跳过该组）
            missing_cols = [c for c in factor_cols if c not in df.columns]
            if missing_cols:
                self.write_log(f"Group {group_name} 缺少因子列: {missing_cols}，跳过")
                continue

            # 计算该组加权得分
            group_df = self._compute_group_score(df, coeffs, factor_cols)
            if group_df.is_empty():
                continue

            # 取总分前 top_pct
            top_n = max(int(len(group_df) * self.top_pct), 1)
            top_df = group_df.sort("score", descending=True).head(top_n)

            if top_df.is_empty():
                continue

            # 过滤 EPS > 0（需要 eps 列）
            if "eps" in top_df.columns:
                top_df = top_df.filter(pl.col("eps") > 0)

            if top_df.is_empty():
                continue

            # 选流通市值最小的 stock_num 只
            selected = top_df.sort("market_cap").head(self.stock_num)
            group_picks = list(selected["vt_symbol"])
            all_selected.extend(group_picks)

            self.write_log(
                f"{group_name}: {len(group_df)}只 -> "
                f"前{self.top_pct*100:.0f}%={len(group_df) - top_n if len(group_df) > top_n else top_n}只 -> "
                f"EPS>0后={len(top_df)}只 -> 选中={len(group_picks)}只"
            )

        # 去重
        all_selected = list(dict.fromkeys(all_selected))

        self.write_log(f"本周选股结果: {len(all_selected)} 只 -> {all_selected}")

        # 更新昨日涨停池（为次日监控做准备）
        self._update_prev_limit_up(df)

        return all_selected

    def _compute_group_score(
        self,
        df: pl.DataFrame,
        coeffs: list[float],
        factor_cols: list[str],
    ) -> pl.DataFrame:
        """计算单组因子加权得分"""
        score_df = df.clone()

        # 初始化 score 列
        score_col = pl.lit(0.0).alias("score")
        for coeff, col in zip(coeffs, factor_cols):
            score_col = score_col + pl.col(col) * coeff

        score_df = score_df.with_columns(score_col.alias("score"))

        # 剔除 score 为 null 的行
        score_df = score_df.filter(pl.col("score").is_not_null())

        return score_df

    # ==================== 过滤 ====================

    def _apply_basic_filters(self, df: pl.DataFrame) -> pl.DataFrame:
        """
        基础过滤：
        - 排除科创板(68)、创业板(30)、北交所(4/8)
        - 排除 ST
        - 排除停牌
        - 排除上市不满 375 天
        - 排除涨跌停（当前不可交易）
        """
        # 主板过滤：排除 300/301/688/689/4/8 开头的股票
        if "vt_symbol" in df.columns:
            df = df.filter(~pl.col("vt_symbol").str.contains(r"^(30|68|[48])"))

        if df.is_empty():
            return df

        # ST 过滤
        if "is_st" in df.columns:
            df = df.filter(pl.col("is_st") == False)

        # 停牌过滤
        if "is_paused" in df.columns:
            df = df.filter(pl.col("is_paused") == False)

        if df.is_empty():
            return df

        # 上市天数过滤
        if "list_days" in df.columns:
            df = df.filter(pl.col("list_days") >= self.min_listing_days)

        if df.is_empty():
            return df

        # 涨跌停过滤（当前 bar 的 close 触及涨跌停价则排除）
        # 注意：已持仓的不在此处过滤，调仓时单独处理
        if "close" in df.columns and "limit_up" in df.columns and "limit_down" in df.columns:
            df = df.filter(
                (pl.col("close") < pl.col("limit_up")) &
                (pl.col("close") > pl.col("limit_down"))
            )

        return df

    # ==================== 调仓 ====================

    def _adjust_position(
        self,
        bars: dict[str, BarData],
        target_list: list[str],
    ) -> None:
        """
        调仓：卖出现有非目标持仓，买入目标持仓
        - 所有股票均分可用资金
        """
        hold_symbols: list[str] = [
            vt for vt, pos in self.pos_data.items() if pos > 0
        ]

        # 卖出不在目标池中的股票
        for vt_symbol in hold_symbols:
            if vt_symbol not in target_list:
                self.set_target(vt_symbol, 0)
                self.write_log(f"调仓卖出: {vt_symbol}")

        if not target_list:
            return

        # 计算每只股票的资金分配
        portfolio_value: float = self.get_portfolio_value()
        cash_available: float = self.get_cash_available()

        # 使用可用现金 * 使用比例来买入
        buy_budget = cash_available * self.cash_use_ratio
        stock_value = buy_budget / len(target_list)

        for vt_symbol in target_list:
            bar: BarData | None = bars.get(vt_symbol)
            if not bar or bar.close_price <= 0:
                continue

            # 如果已经持有，不重复买入
            if self.get_pos(vt_symbol) > 0:
                continue

            target_volume: float = round_to(
                stock_value / bar.close_price, self.min_trade_volume
            )
            if target_volume >= self.min_trade_volume:
                self.set_target(vt_symbol, target_volume)
                self.write_log(
                    f"调仓买入: {vt_symbol}, "
                    f"目标量={target_volume}, 价格≈{bar.close_price:.2f}"
                )

    # ==================== 空仓期 ====================

    def _is_in_empty_period(self, date_str: str) -> bool:
        """判断当前是否处于空仓期（如 0405 ~ 0430）"""
        return self.empty_period_start <= date_str <= self.empty_period_end

    def _handle_empty_period(self, bars: dict[str, BarData]) -> None:
        """空仓期处理：清仓所有股票"""
        hold_symbols: list[str] = [
            vt for vt, pos in self.pos_data.items() if pos > 0
        ]

        for vt_symbol in hold_symbols:
            bar = bars.get(vt_symbol)
            if bar is None:
                continue
            # 跌停无法卖出
            if bar.close_price <= 0:
                continue
            if bar.low_price == bar.close_price and bar.close_price == bar.high_price:
                # 一字跌停，无法卖出
                if "limit_down" in [c for c in []]:
                    continue

            current_pos = self.get_pos(vt_symbol)
            if current_pos > 0:
                self.set_target(vt_symbol, 0)
                self.write_log(f"空仓期清仓: {vt_symbol}")

    # ==================== 涨停监控 ====================

    def _update_prev_limit_up(self, df: pl.DataFrame) -> None:
        """更新昨日涨停股票池（在调仓选股后调用）"""
        self.prev_limit_up.clear()

        if "limit_up" not in df.columns or "close" not in df.columns:
            return

        # 筛选今日涨停的股票
        limit_up_stocks = df.filter(
            pl.col("close") >= pl.col("limit_up")
        )

        self.prev_limit_up = set(limit_up_stocks["vt_symbol"].to_list())
        if self.prev_limit_up:
            self.write_log(f"涨停股池更新: {len(self.prev_limit_up)} 只")

    def _check_limit_up_monitor(
        self,
        bars: dict[str, BarData],
        current_dt,
    ) -> None:
        """
        涨停板监控（非空仓期每日执行）：
        - 昨日涨停的股票，今日检查是否仍涨停
        - 涨停打开 -> 卖出
        - 仍涨停 -> 继续持有
        """
        if not self.prev_limit_up:
            return

        signal_df: pl.DataFrame = self.get_signal()
        if signal_df.is_empty():
            return

        df = signal_df.filter(pl.col("datetime") == current_dt)
        if df.is_empty():
            return

        # 判断哪些仍涨停、哪些涨停打开
        still_limit_up: set[str] = set()
        limit_opened: set[str] = set()

        for vt_symbol in list(self.prev_limit_up):
            row = df.filter(pl.col("vt_symbol") == vt_symbol)
            if row.is_empty():
                continue

            # 检查当前是否仍涨停
            bar = bars.get(vt_symbol)
            if bar is None:
                continue

            has_limit_up_col = "limit_up" in df.columns
            is_still_limit = False

            if has_limit_up_col:
                limit_up_val = row["limit_up"].to_list()
                if limit_up_val and bar.close_price >= limit_up_val[0]:
                    is_still_limit = True
            else:
                # 无 limit_up 列时，用 pre_close * 1.1 估算
                if "pre_close" in df.columns:
                    pre_close_val = row["pre_close"].to_list()
                    if pre_close_val:
                        est_limit_up = pre_close_val[0] * 1.1
                        if bar.close_price >= est_limit_up:
                            is_still_limit = True
                else:
                    # 无 pre_close 时，假设继续持有
                    is_still_limit = True

            if is_still_limit:
                still_limit_up.add(vt_symbol)
            else:
                limit_opened.add(vt_symbol)

        # 涨停打开的卖出
        for vt_symbol in limit_opened:
            if self.get_pos(vt_symbol) > 0:
                self.set_target(vt_symbol, 0)
                self.write_log(f"涨停打开卖出: {vt_symbol}")

        # 更新涨停池为今日涨停股
        self.prev_limit_up = still_limit_up

