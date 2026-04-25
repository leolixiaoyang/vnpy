"""
ML 因子小市值策略信号生成管线
==============================
从 Tushare 获取原始数据，计算所有 ML 因子，输出 signal_df。

signal_df 列说明：
  基础列：datetime, vt_symbol, market_cap, eps, list_days,
           is_paused, is_st, close, pre_close, limit_up, limit_down

  Group 1 因子：arbr, sgai, net_profit_margin_ttm, retained_profit_per_share
  Group 2 因子：price_1y, total_profit_to_cost_ratio, vol120
  Group 3 因子：price_no_fq, total_profit_to_cost_ratio, inventory_turnover_rate
  Group 4 因子：debt_to_assets, operating_cost_to_revenue_ratio, davol20,
                price_no_fq, sales_growth_5y
  Group 5 因子：tvstd6, cashflow_per_share_ttm, sharpe_ratio_120,
                non_operating_net_profit_ttm

因子计算说明：
  - 技术类因子（ARBR、VOL、DAVOL、TVSTD、Sharpe、price_1y）从日线数据计算
  - 基本面因子（SGAI、净利率、ROE、负债率等）从财报数据获取，向后填充避免未来函数
  - price_no_fq 使用不复权日线价格
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import numpy as np
import polars as pl
import tinyshare as ts


@dataclass
class SignalConfig:
    """信号构建参数。"""
    ts_codes: list[str]
    start_date: str
    end_date: str
    token: str


def _to_vt_symbol(ts_code: str) -> str:
    return ts_code.replace(".SZ", ".SZSE").replace(".SH", ".SSE")


class MlFactorSignalPipeline:
    """ML 因子信号管线"""

    def __init__(self, config: SignalConfig) -> None:
        self.config: SignalConfig = config

    def generate(self) -> pl.DataFrame:
        """生成包含所有 ML 因子的 signal_df。"""
        ts.set_token(self.config.token)
        pro = ts.pro_api()

        frames: list[pl.DataFrame] = []

        for i, ts_code in enumerate(self.config.ts_codes):
            if (i + 1) % 50 == 0:
                print(f"  处理进度: {i+1}/{len(self.config.ts_codes)}")

            # 获取不复权价格（用于 price_no_fq 因子）
            daily_unfq = self._get_daily(pro, ts_code, adj=None)
            # 获取后复权价格（用于常规技术指标）
            daily = self._get_daily(pro, ts_code, adj="hfq")

            if daily is None or len(daily) == 0:
                continue

            daily_df = pl.DataFrame(daily).sort("trade_date")


            # 合并基本面数据
            daily_df = self._merge_daily_basic(pro, ts_code, daily_df)
            daily_df = self._merge_fina_indicator(pro, ts_code, daily_df)
            daily_df = self._merge_cashflow(pro, ts_code, daily_df)
            daily_df = self._merge_income(pro, ts_code, daily_df)
            daily_df = self._merge_balance(pro, ts_code, daily_df)

            close_arr = daily_df["close"].to_numpy()
            open_arr = daily_df["open"].to_numpy()
            high_arr = daily_df["high"].to_numpy()
            low_arr = daily_df["low"].to_numpy()
            vol_arr = daily_df["vol"].to_numpy()
            amount_arr = daily_df["amount"].to_numpy()

            # ====== 技术因子 ======

            # ARBR 情绪指标
            ar_values = self._calc_ar(open_arr, high_arr, low_arr)
            br_values = self._calc_br(close_arr, high_arr, low_arr)
            arbr_values = (ar_values + br_values) / 2.0

            # 120日平均换手率（需要流通股本，用 vol / float_share 估算）
            vol120 = self._rolling_mean(vol_arr, 120)

            # 20日/120日平均换手率之比
            vol20_mean = self._rolling_mean(vol_arr, 20)
            davol20 = np.where(vol120 > 0, vol20_mean / vol120, np.nan)

            # 6日成交金额标准差
            tvstd6 = self._rolling_std(amount_arr, 6)

            # 股价相对年均价偏离 (price_1y)
            mean_250 = self._rolling_mean(close_arr, 250)
            price_1y = np.where(mean_250 > 0, close_arr / mean_250 - 1.0, np.nan)

            # 120日夏普率 (年化)
            daily_ret = close_arr / np.roll(close_arr, 1) - 1.0
            daily_ret[0] = np.nan
            sharpe_120 = self._rolling_sharpe(daily_ret, 120, ann=250)

            # 涨跌停价格
            pre_close_arr = np.roll(close_arr, 1)
            pre_close_arr[0] = np.nan
            limit_up_arr = np.round(pre_close_arr * 1.1, 2)
            limit_down_arr = np.round(pre_close_arr * 0.9, 2)

            # ====== 组装 DataFrame ======

            daily_df = daily_df.with_columns([
                pl.lit(datetime.now()).alias("_temp"),  # placeholder
                pl.lit(_to_vt_symbol(ts_code)).alias("vt_symbol"),
                pl.lit(False).alias("is_paused"),
                pl.lit(False).alias("is_st"),
                pl.Series("list_days", np.arange(1, len(daily_df) + 1), dtype=pl.Int64),
                pl.Series("arbr", arbr_values, dtype=pl.Float64),
                pl.Series("vol120", vol120, dtype=pl.Float64),
                pl.Series("davol20", davol20, dtype=pl.Float64),
                pl.Series("tvstd6", tvstd6, dtype=pl.Float64),
                pl.Series("price_1y", price_1y, dtype=pl.Float64),
                pl.Series("sharpe_ratio_120", sharpe_120, dtype=pl.Float64),
                pl.Series("pre_close", pre_close_arr, dtype=pl.Float64),
                pl.Series("limit_up", limit_up_arr, dtype=pl.Float64),
                pl.Series("limit_down", limit_down_arr, dtype=pl.Float64),
            ])

            # price_no_fq: 使用不复权价格
            if daily_unfq is not None and len(daily_unfq) > 0:
                unfq_df = pl.DataFrame(daily_unfq).select(["trade_date", "close"])
                unfq_df = unfq_df.rename({"close": "price_no_fq"})
                unfq_df = unfq_df.with_columns(
                    pl.col("trade_date").cast(pl.Utf8)
                )
                daily_df = daily_df.with_columns(
                    pl.col("trade_date").cast(pl.Utf8)
                )
                daily_df = daily_df.join(unfq_df, on="trade_date", how="left")
            else:
                daily_df = daily_df.with_columns(
                    pl.col("close").alias("price_no_fq")
                )

            # ====== 基本面因子列映射 ======
            # 将财务数据列转为 Float64（Tushare 返回的可能是 String）
            float_cols_to_cast = [
                "admin_exp", "revenue", "admin_exp_gr", "net_profit_margin_ttm",
                "netprofit_margin", "n_income", "undistributed_profit", "total_share",
                "undistr_porfit", "total_profit", "oper_cost", "inventory",
                "total_liab", "total_assets", "oper_revenue",
                "non_oper_income", "non_oper_exp", "extra_item",
                "cfps", "ncfps", "n_cashflow_act",
                "or_yoy", "debt_to_assets", "circ_mv", "eps",
            ]
            for col in float_cols_to_cast:
                if col in daily_df.columns:
                    try:
                        daily_df = daily_df.with_columns(
                            pl.col(col).cast(pl.Float64, strict=False)
                        )
                    except Exception:
                        pass

            # SGAI: 销售管理费用率 = 管理费用 / 营业收入
            if "admin_exp" in daily_df.columns and "revenue" in daily_df.columns:
                daily_df = daily_df.with_columns(
                    (pl.col("admin_exp") / pl.col("revenue")).alias("sgai")
                )
            elif "admin_exp_gr" in daily_df.columns:
                # 如果直接用 fina_indicator 的管理费用率
                daily_df = daily_df.with_columns(
                    pl.col("admin_exp_gr").alias("sgai")
                )

            # net_profit_margin_ttm: 净利率 TTM
            if "net_profit_margin_ttm" not in daily_df.columns:
                if "netprofit_margin" in daily_df.columns:
                    daily_df = daily_df.with_columns(
                        pl.col("netprofit_margin").alias("net_profit_margin_ttm")
                    )
                elif "n_income" in daily_df.columns and "revenue" in daily_df.columns:
                    daily_df = daily_df.with_columns(
                        (pl.col("n_income") / pl.col("revenue")).alias("net_profit_margin_ttm")
                    )

            # retained_profit_per_share: 每股未分配利润
            if "bps_urps" not in daily_df.columns:
                if "undistributed_profit" in daily_df.columns and "total_share" in daily_df.columns:
                    daily_df = daily_df.with_columns(
                        (pl.col("undistributed_profit") / pl.col("total_share")).alias("retained_profit_per_share")
                    )
                elif "undistr_porfit" in daily_df.columns and "total_share" in daily_df.columns:
                    daily_df = daily_df.with_columns(
                        (pl.col("undistr_porfit") / pl.col("total_share")).alias("retained_profit_per_share")
                    )

            # total_profit_to_cost_ratio: 成本费用利润率 = 利润总额 / 营业成本
            if "total_profit" in daily_df.columns and "oper_cost" in daily_df.columns:
                daily_df = daily_df.with_columns(
                    (pl.col("total_profit") / pl.col("oper_cost")).alias("total_profit_to_cost_ratio")
                )

            # inventory_turnover_rate: 存货周转率 = 营业成本 / 平均存货
            if "oper_cost" in daily_df.columns and "inventory" in daily_df.columns:
                daily_df = daily_df.with_columns(
                    (pl.col("oper_cost") / pl.col("inventory")).alias("inventory_turnover_rate")
                )

            # debt_to_assets: 资产负债率
            if "debt_to_assets" not in daily_df.columns:
                if "total_liab" in daily_df.columns and "total_assets" in daily_df.columns:
                    daily_df = daily_df.with_columns(
                        (pl.col("total_liab") / pl.col("total_assets")).alias("debt_to_assets")
                    )

            # operating_cost_to_revenue_ratio: 销售成本率 = 营业成本 / 营业收入
            if "oper_cost" in daily_df.columns and "revenue" in daily_df.columns:
                daily_df = daily_df.with_columns(
                    (pl.col("oper_cost") / pl.col("revenue")).alias("operating_cost_to_revenue_ratio")
                )

            # sales_growth_5y: 5年营收增长率 (用年化增速近似)
            if "or_yoy" in daily_df.columns:
                daily_df = daily_df.with_columns(
                    pl.col("or_yoy").alias("sales_growth_5y")
                )

            # cashflow_per_share_ttm: 每股现金流量净额 TTM
            if "cfps" in daily_df.columns:
                daily_df = daily_df.with_columns(
                    pl.col("cfps").alias("cashflow_per_share_ttm")
                )
            elif "ncfps" in daily_df.columns:
                daily_df = daily_df.with_columns(
                    pl.col("ncfps").alias("cashflow_per_share_ttm")
                )
            elif "n_cashflow_act" in daily_df.columns and "total_share" in daily_df.columns:
                daily_df = daily_df.with_columns(
                    (pl.col("n_cashflow_act") / pl.col("total_share")).alias("cashflow_per_share_ttm")
                )

            # non_operating_net_profit_ttm: 营业外收支净额
            if "non_oper_income" in daily_df.columns and "non_oper_exp" in daily_df.columns:
                daily_df = daily_df.with_columns(
                    (pl.col("non_oper_income") - pl.col("non_oper_exp")).alias("non_operating_net_profit_ttm")
                )
            elif "non_operate_profit" in daily_df.columns:
                daily_df = daily_df.with_columns(
                    pl.col("non_operate_profit").alias("non_operating_net_profit_ttm")
                )
            elif "extra_item" in daily_df.columns:
                daily_df = daily_df.with_columns(
                    pl.col("extra_item").alias("non_operating_net_profit_ttm")
                )

            # market_cap: 流通市值
            if "circ_mv" in daily_df.columns:
                daily_df = daily_df.with_columns(
                    pl.col("circ_mv").cast(pl.Float64).alias("market_cap")
                )
            else:
                daily_df = daily_df.with_columns(
                    (pl.col("close") * pl.col("vol") * 100).alias("market_cap")
                )

            # EPS
            if "eps" not in daily_df.columns:
                if "n_income" in daily_df.columns and "total_share" in daily_df.columns:
                    daily_df = daily_df.with_columns(
                        (pl.col("n_income") / pl.col("total_share")).alias("eps")
                    )

            # 转换 datetime 列
            try:
                daily_df = daily_df.with_columns(
                    pl.col("trade_date").str.to_datetime("%Y%m%d").alias("datetime")
                )
            except Exception:
                dates = [datetime.strptime(str(d), "%Y%m%d") for d in daily_df["trade_date"].to_list()]
                daily_df = daily_df.with_columns(
                    pl.Series("datetime", dates, dtype=pl.Datetime)
                )

            # 选择需要的列
            select_cols = [
                "datetime", "vt_symbol", "market_cap", "close", "pre_close",
                "limit_up", "limit_down", "list_days", "is_paused", "is_st",
                "arbr", "vol120", "davol20", "tvstd6", "price_1y",
                "sharpe_ratio_120", "price_no_fq",
            ]

            # 可选基本面列（存在时才加入）
            optional_cols = [
                "sgai", "net_profit_margin_ttm", "retained_profit_per_share",
                "total_profit_to_cost_ratio", "inventory_turnover_rate",
                "debt_to_assets", "operating_cost_to_revenue_ratio",
                "sales_growth_5y", "cashflow_per_share_ttm",
                "non_operating_net_profit_ttm", "eps",
            ]
            for col in optional_cols:
                if col in daily_df.columns:
                    select_cols.append(col)

            select_cols = [c for c in select_cols if c in daily_df.columns]

            frames.append(daily_df.select(select_cols))

        if not frames:
            return pl.DataFrame()

        signal_df = pl.concat(frames, how="vertical").sort(["datetime", "vt_symbol"])

        # 财务数据向后填充（避免未来函数）
        fill_cols = [
            "sgai", "net_profit_margin_ttm", "retained_profit_per_share",
            "total_profit_to_cost_ratio", "inventory_turnover_rate",
            "debt_to_assets", "operating_cost_to_revenue_ratio",
            "sales_growth_5y", "cashflow_per_share_ttm",
            "non_operating_net_profit_ttm", "eps",
        ]
        for col in fill_cols:
            if col in signal_df.columns:
                signal_df = signal_df.with_columns(
                    pl.col(col).fill_nan(None).fill_null(strategy="forward").over("vt_symbol")
                )

        return signal_df

    def _get_daily(self, pro, ts_code: str, adj: str | None = None) -> list[dict] | None:
        """获取日线数据。"""
        try:
            is_fund = ts_code.startswith("51") or ts_code.startswith("15")
            if is_fund:
                return pro.fund_daily(
                    ts_code=ts_code,
                    start_date=self._to_ts_date(self.config.start_date),
                    end_date=self._to_ts_date(self.config.end_date),
                )
            else:
                return pro.daily(
                    ts_code=ts_code,
                    start_date=self._to_ts_date(self.config.start_date),
                    end_date=self._to_ts_date(self.config.end_date),
                    adj=adj,
                )
        except Exception:
            return None

    def _merge_daily_basic(self, pro, ts_code: str, df: pl.DataFrame) -> pl.DataFrame:
        """合并日度基本面数据。"""
        try:
            basic = pro.daily_basic(
                ts_code=ts_code,
                start_date=self._to_ts_date(self.config.start_date),
                end_date=self._to_ts_date(self.config.end_date),
                fields="ts_code,trade_date,pe,pb,total_mv,circ_mv,eps,turnover_rate",
            )
            if basic and len(basic) > 0:
                basic_df = pl.DataFrame(basic)
                df = df.join(basic_df, on=["ts_code", "trade_date"], how="left")
        except Exception:
            pass
        return df

    def _merge_fina_indicator(self, pro, ts_code: str, df: pl.DataFrame) -> pl.DataFrame:
        """合并财务指标（asof_join 匹配最近财报日）。"""
        try:
            fina = pro.fina_indicator(ts_code=ts_code)
            if fina is None or (hasattr(fina, "empty") and fina.empty):
                return df
            import pandas as pd
            if isinstance(fina, pd.DataFrame):
                fina_df = pl.from_pandas(fina)
            else:
                fina_df = pl.DataFrame(fina)
            # 按报告期过滤（start_date/end_date 是公告日，不是报告期）
            start = self._to_ts_date(self.config.start_date)
            end = self._to_ts_date(self.config.end_date)
            fina_df = fina_df.filter((pl.col("end_date") >= start) & (pl.col("end_date") <= end))
            if fina_df.is_empty():
                return df
            fina_df = fina_df.rename({
                "end_date": "report_date",
                "netprofit_margin": "net_profit_margin_ttm",
                "adminexp_of_gr": "admin_exp_gr",
            }).sort("report_date")
            df = df.with_columns(pl.col("trade_date").cast(pl.Utf8))
            fina_df = fina_df.with_columns(pl.col("report_date").cast(pl.Utf8))
            df = df.join_asof(
                fina_df,
                left_on="trade_date",
                right_on="report_date",
                by="ts_code",
                strategy="backward",
                suffix="_fina",
            )
        except Exception as e:
            print(f"  [ERROR] fina_indicator failed for {ts_code}: {e}")
        return df

    def _merge_cashflow(self, pro, ts_code: str, df: pl.DataFrame) -> pl.DataFrame:
        """合并现金流量表（asof_join）。"""
        try:
            cash = pro.cashflow(ts_code=ts_code)
            if cash is None or (hasattr(cash, "empty") and cash.empty):
                return df
            import pandas as pd
            if isinstance(cash, pd.DataFrame):
                cash_df = pl.from_pandas(cash)
            else:
                cash_df = pl.DataFrame(cash)
            start = self._to_ts_date(self.config.start_date)
            end = self._to_ts_date(self.config.end_date)
            cash_df = cash_df.filter((pl.col("end_date") >= start) & (pl.col("end_date") <= end))
            if cash_df.is_empty():
                return df
            cash_df = cash_df.rename({"end_date": "report_date"}).sort("report_date")
            df = df.with_columns(pl.col("trade_date").cast(pl.Utf8))
            cash_df = cash_df.with_columns(pl.col("report_date").cast(pl.Utf8))
            df = df.join_asof(
                cash_df,
                left_on="trade_date",
                right_on="report_date",
                by="ts_code",
                strategy="backward",
                suffix="_cash",
            )
        except Exception as e:
            print(f"  [ERROR] cashflow failed for {ts_code}: {e}")
        return df

    def _merge_income(self, pro, ts_code: str, df: pl.DataFrame) -> pl.DataFrame:
        """合并利润表（asof_join）。"""
        try:
            income = pro.income(ts_code=ts_code)
            if income is None or (hasattr(income, "empty") and income.empty):
                return df
            import pandas as pd
            if isinstance(income, pd.DataFrame):
                income_df = pl.from_pandas(income)
            else:
                income_df = pl.DataFrame(income)
            start = self._to_ts_date(self.config.start_date)
            end = self._to_ts_date(self.config.end_date)
            income_df = income_df.filter((pl.col("end_date") >= start) & (pl.col("end_date") <= end))
            if income_df.is_empty():
                return df
            income_df = income_df.rename({"end_date": "report_date"}).sort("report_date")
            df = df.with_columns(pl.col("trade_date").cast(pl.Utf8))
            income_df = income_df.with_columns(pl.col("report_date").cast(pl.Utf8))
            df = df.join_asof(
                income_df,
                left_on="trade_date",
                right_on="report_date",
                by="ts_code",
                strategy="backward",
                suffix="_inc",
            )
        except Exception as e:
            print(f"  [ERROR] income failed for {ts_code}: {e}")
        return df

    def _merge_balance(self, pro, ts_code: str, df: pl.DataFrame) -> pl.DataFrame:
        """合并资产负债表（asof_join）。"""
        try:
            balance = pro.balancesheet(ts_code=ts_code)
            if balance is None or (hasattr(balance, "empty") and balance.empty):
                return df
            import pandas as pd
            if isinstance(balance, pd.DataFrame):
                balance_df = pl.from_pandas(balance)
            else:
                balance_df = pl.DataFrame(balance)
            start = self._to_ts_date(self.config.start_date)
            end = self._to_ts_date(self.config.end_date)
            balance_df = balance_df.filter((pl.col("end_date") >= start) & (pl.col("end_date") <= end))
            if balance_df.is_empty():
                return df
            balance_df = balance_df.rename({
                "end_date": "report_date",
                "undistr_porfit": "undistributed_profit",
                "inventories": "inventory",
            }).sort("report_date")
            df = df.with_columns(pl.col("trade_date").cast(pl.Utf8))
            balance_df = balance_df.with_columns(pl.col("report_date").cast(pl.Utf8))
            df = df.join_asof(
                balance_df,
                left_on="trade_date",
                right_on="report_date",
                by="ts_code",
                strategy="backward",
                suffix="_bal",
            )
        except Exception as e:
            print(f"  [ERROR] balance failed for {ts_code}: {e}")
        return df

    # ==================== 技术指标计算 ====================

    @staticmethod
    def _calc_ar(open_arr: np.ndarray, high_arr: np.ndarray, low_arr: np.ndarray) -> np.ndarray:
        """AR 指标：N 日内 (H-O) 之和 / (O-L) 之和 * 100"""
        result = np.full(len(open_arr), np.nan)
        n = 26
        for i in range(n, len(open_arr)):
            h_o = np.sum(high_arr[i-n+1:i+1] - open_arr[i-n+1:i+1])
            o_l = np.sum(open_arr[i-n+1:i+1] - low_arr[i-n+1:i+1])
            if o_l > 0:
                result[i] = (h_o / o_l) * 100
        return result

    @staticmethod
    def _calc_br(close_arr: np.ndarray, high_arr: np.ndarray, low_arr: np.ndarray) -> np.ndarray:
        """BR 指标：N 日内 (H-PreC) 之和 / (PreC-L) 之和 * 100"""
        result = np.full(len(close_arr), np.nan)
        n = 26
        pre_close = np.roll(close_arr, 1)
        for i in range(n + 1, len(close_arr)):
            h_pc = np.sum(high_arr[i-n+1:i+1] - pre_close[i-n+1:i+1])
            pc_l = np.sum(pre_close[i-n+1:i+1] - low_arr[i-n+1:i+1])
            if pc_l > 0:
                result[i] = (h_pc / pc_l) * 100
        return result

    @staticmethod
    def _rolling_mean(values: np.ndarray, window: int) -> np.ndarray:
        result = np.full(values.shape, np.nan)
        for i in range(window - 1, len(values)):
            result[i] = float(np.nanmean(values[i - window + 1: i + 1]))
        return result

    @staticmethod
    def _rolling_std(values: np.ndarray, window: int) -> np.ndarray:
        result = np.full(values.shape, np.nan)
        for i in range(window - 1, len(values)):
            result[i] = float(np.nanstd(values[i - window + 1: i + 1]))
        return result

    @staticmethod
    def _rolling_sharpe(returns: np.ndarray, window: int, ann: int = 250) -> np.ndarray:
        result = np.full(len(returns), np.nan)
        for i in range(window, len(returns)):
            subset = returns[i - window + 1: i + 1]
            mean_ret = np.nanmean(subset)
            std_ret = np.nanstd(subset)
            if std_ret > 0:
                result[i] = (mean_ret / std_ret) * np.sqrt(ann)
        return result

    @staticmethod
    def _to_ts_date(value: str) -> str:
        return value.replace("-", "")
