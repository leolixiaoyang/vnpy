"""小市值策略信号生成。"""

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
    """把 tushare 代码转换成 vnpy vt_symbol。"""
    return ts_code.replace(".SZ", ".SZSE").replace(".SH", ".SSE")


class SmallCapSignalPipeline:
    """构建小市值策略所需信号数据。"""

    def __init__(self, config: SignalConfig) -> None:
        self.config: SignalConfig = config

    def generate(self) -> pl.DataFrame:
        """生成 signal_df。"""
        ts.set_token(self.config.token)
        pro = ts.pro_api()

        frames: list[pl.DataFrame] = []

        for ts_code in self.config.ts_codes:
            daily = pro.daily(
                ts_code=ts_code,
                start_date=self._to_ts_date(self.config.start_date),
                end_date=self._to_ts_date(self.config.end_date),
            )
            if daily is None or len(daily) == 0:
                continue

            basic = None
            fina = None
            cash = None

            try:
                basic = pro.daily_basic(
                    ts_code=ts_code,
                    start_date=self._to_ts_date(self.config.start_date),
                    end_date=self._to_ts_date(self.config.end_date),
                    fields="ts_code,trade_date,pe,pb,total_mv,circ_mv",
                )
            except Exception:
                basic = None

            try:
                fina = pro.fina_indicator(
                    ts_code=ts_code,
                    fields="ts_code,end_date,roe,profit_dedt",
                    start_date=self._to_ts_date(self.config.start_date),
                    end_date=self._to_ts_date(self.config.end_date),
                )
            except Exception:
                fina = None

            try:
                cash = pro.cashflow(
                    ts_code=ts_code,
                    fields="ts_code,end_date,n_cashflow_act",
                    start_date=self._to_ts_date(self.config.start_date),
                    end_date=self._to_ts_date(self.config.end_date),
                )
            except Exception:
                cash = None

            daily_df = pl.DataFrame(daily).sort("trade_date")

            if basic is not None and len(basic) > 0:
                basic_df = pl.DataFrame(basic)
                daily_df = daily_df.join(basic_df, on=["ts_code", "trade_date"], how="left")

            # 财务指标按公告日期向后填充，避免未来函数
            if fina is not None and len(fina) > 0:
                fina_df = (
                    pl.DataFrame(fina)
                    .rename({"end_date": "trade_date", "profit_dedt": "net_profit"})
                    .sort("trade_date")
                    .select(["trade_date", "roe", "net_profit"])
                )
                daily_df = daily_df.join(fina_df, on="trade_date", how="left")

            if cash is not None and len(cash) > 0:
                cash_df = (
                    pl.DataFrame(cash)
                    .rename({"end_date": "trade_date", "n_cashflow_act": "net_operate_cash_flow"})
                    .sort("trade_date")
                    .select(["trade_date", "net_operate_cash_flow"])
                )
                daily_df = daily_df.join(cash_df, on="trade_date", how="left")

            # 计算技术字段
            close_arr = daily_df["close"].to_numpy()
            vol20 = self._rolling_std(self._pct_change(close_arr), 20)
            ma10 = self._rolling_mean(close_arr, 10)
            ma20 = self._rolling_mean(close_arr, 20)
            recent_drop = self._rolling_min(self._pct_change(close_arr), 5) <= -0.08

            # 上市天数
            list_days = np.arange(1, len(daily_df) + 1)

            daily_df = daily_df.with_columns([
                pl.Series("datetime", self._to_datetime_series(daily_df["trade_date"].to_list()), dtype=pl.Datetime),
                pl.lit(_to_vt_symbol(ts_code)).alias("vt_symbol"),
                pl.lit(False).alias("is_paused"),
                pl.lit(False).alias("is_st"),
                pl.Series("list_days", list_days, dtype=pl.Int64),
                pl.Series("vol20", vol20, dtype=pl.Float64),
                pl.Series("ma10", ma10, dtype=pl.Float64),
                pl.Series("ma20", ma20, dtype=pl.Float64),
                pl.Series("recent_drop", recent_drop, dtype=pl.Boolean),
            ])

            # 用 circ_mv 作为市值，缺失时退化为成交额近似值
            if "circ_mv" in daily_df.columns:
                daily_df = daily_df.with_columns(pl.col("circ_mv").cast(pl.Float64).alias("market_cap"))
            else:
                daily_df = daily_df.with_columns((pl.col("close") * pl.col("vol") * 100).alias("market_cap"))

            frames.append(
                daily_df.select([
                    "datetime",
                    "vt_symbol",
                    "market_cap",
                    pl.col("pb").cast(pl.Float64).alias("pb_ratio"),
                    pl.col("pe").cast(pl.Float64).alias("pe_ratio"),
                    pl.col("roe").cast(pl.Float64).alias("roe"),
                    pl.col("net_profit").cast(pl.Float64).alias("net_profit"),
                    pl.col("net_operate_cash_flow").cast(pl.Float64).alias("net_operate_cash_flow"),
                    "list_days",
                    "is_paused",
                    "is_st",
                    "recent_drop",
                    pl.col("close").cast(pl.Float64).alias("close"),
                    "vol20",
                    "ma10",
                    "ma20",
                ])
            )

        if not frames:
            return pl.DataFrame()

        signal_df = pl.concat(frames, how="vertical").sort(["datetime", "vt_symbol"])

        # 把财务空值向后填充，并做最小字段清洗
        signal_df = signal_df.with_columns([
            pl.col("pb_ratio").fill_nan(None).fill_null(strategy="forward").over("vt_symbol"),
            pl.col("pe_ratio").fill_nan(None).fill_null(strategy="forward").over("vt_symbol"),
            pl.col("roe").fill_nan(None).fill_null(strategy="forward").over("vt_symbol"),
            pl.col("net_profit").fill_nan(None).fill_null(strategy="forward").over("vt_symbol"),
            pl.col("net_operate_cash_flow").fill_nan(None).fill_null(strategy="forward").over("vt_symbol"),
        ])

        return signal_df

    @staticmethod
    def _to_ts_date(value: str) -> str:
        return value.replace("-", "")

    @staticmethod
    def _to_datetime_series(date_strs: list[str]) -> list[datetime]:
        return [datetime.strptime(d, "%Y%m%d") for d in date_strs]

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
    def _rolling_min(values: np.ndarray, window: int) -> np.ndarray:
        result = np.full(values.shape, np.nan)
        for i in range(window - 1, len(values)):
            result[i] = float(np.nanmin(values[i - window + 1: i + 1]))
        return result

    @staticmethod
    def _pct_change(values: np.ndarray) -> np.ndarray:
        output = values / np.roll(values, 1) - 1.0
        output[0] = np.nan
        return output
