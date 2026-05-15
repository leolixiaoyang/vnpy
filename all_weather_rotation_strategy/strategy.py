from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd

from config import (
    BIG_INDEX_CODE,
    BUY_PRICE_SLIPPAGE,
    CASH_USAGE_RATIO,
    CLOSE_COMMISSION,
    CLOSE_TAX,
    FALLBACK_BIG_POOL,
    FALLBACK_SMALL_POOL,
    FOREIGN_ETF,
    LOOKBACK_DAYS,
    MIN_LISTING_DAYS,
    MIN_TRADE_VOLUME,
    OPEN_COMMISSION,
    SELL_PRICE_SLIPPAGE,
    SMALL_INDEX_CODE,
    STOCK_NUM,
    STOP_LOSS_RATE,
)
from data_client import TinyshareClient


@dataclass
class Position:
    ts_code: str
    volume: int
    avg_cost: float


class AllWeatherRotationBacktester:
    """使用 tinyshare 复刻 JoinQuant 全天候轮动策略的回测器。"""

    def __init__(self, client: TinyshareClient, start_date: str, end_date: str, initial_capital: float) -> None:
        self.client = client
        self.start_date = start_date
        self.end_date = end_date
        self.initial_capital = float(initial_capital)

        self.cash: float = float(initial_capital)
        self.positions: dict[str, Position] = {}
        self.hold_list: list[str] = []
        self.yesterday_hl_list: list[str] = []
        self.trades: list[dict[str, Any]] = []
        self.equity_curve: list[dict[str, Any]] = []

        self._daily_cache: dict[str, pd.DataFrame] = {}
        self._stock_basic: pd.DataFrame = self.client.stock_basic()
        self._calendar = self._build_calendar()

    def run(self) -> tuple[pd.DataFrame, pd.DataFrame]:
        if self._calendar.empty:
            raise ValueError("未获取到交易日历，无法回测")

        dates = self._calendar["trade_date"].tolist()
        for i, trade_date in enumerate(dates):
            prev_date = dates[i - 1] if i > 0 else trade_date

            self.prepare_stock_list(prev_date)
            self.stop_loss(trade_date)

            if i == 0 or trade_date[:6] != prev_date[:6]:
                self.monthly_adjustment(trade_date, prev_date)

            self._record_equity(trade_date)

        trades_df = pd.DataFrame(self.trades)
        equity_df = pd.DataFrame(self.equity_curve)
        return trades_df, equity_df

    def _build_calendar(self) -> pd.DataFrame:
        df = self.client.daily(
            ts_code=BIG_INDEX_CODE,
            start_date=self.start_date,
            end_date=self.end_date,
            adj=None,
        )
        if df.empty:
            return pd.DataFrame(columns=["trade_date"])
        return df[["trade_date"]].drop_duplicates().sort_values("trade_date").reset_index(drop=True)

    def _load_daily(self, ts_code: str) -> pd.DataFrame:
        if ts_code in self._daily_cache:
            return self._daily_cache[ts_code]
        df = self.client.daily(
            ts_code=ts_code,
            start_date=self.start_date,
            end_date=self.end_date,
            adj=None,
        )
        if not df.empty:
            for col in ["open", "high", "low", "close", "pre_close", "vol", "amount"]:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors="coerce")
        self._daily_cache[ts_code] = df
        return df

    def _bar_on(self, ts_code: str, trade_date: str) -> dict[str, Any] | None:
        df = self._load_daily(ts_code)
        if df.empty:
            return None
        day = df[df["trade_date"] == trade_date]
        if day.empty:
            return None
        return day.iloc[-1].to_dict()

    @staticmethod
    def _limit_rate(ts_code: str, is_st: bool = False) -> float:
        if is_st:
            return 0.05
        if ts_code.startswith("300") or ts_code.startswith("688"):
            return 0.20
        if ts_code.startswith("8") or ts_code.startswith("4"):
            return 0.30
        return 0.10

    def _is_st_name(self, ts_code: str) -> bool:
        if self._stock_basic.empty:
            return False
        row = self._stock_basic[self._stock_basic["ts_code"] == ts_code]
        if row.empty:
            return False
        name = str(row.iloc[-1].get("name", ""))
        return ("ST" in name) or ("*" in name) or ("退" in name)

    def _is_new_stock(self, ts_code: str, trade_date: str) -> bool:
        if self._stock_basic.empty:
            return False
        row = self._stock_basic[self._stock_basic["ts_code"] == ts_code]
        if row.empty:
            return False
        list_date = str(row.iloc[-1].get("list_date", ""))
        if len(list_date) != 8:
            return False
        try:
            listed = datetime.strptime(list_date, "%Y%m%d")
            day = datetime.strptime(trade_date, "%Y%m%d")
        except ValueError:
            return False
        return (day - listed).days < MIN_LISTING_DAYS

    @staticmethod
    def _filter_kcbj(stocks: list[str]) -> list[str]:
        out: list[str] = []
        for code in stocks:
            symbol = code.split(".")[0]
            if symbol.startswith(("4", "8", "68", "3")):
                continue
            out.append(code)
        return out

    def _filter_st(self, stocks: list[str]) -> list[str]:
        return [s for s in stocks if not self._is_st_name(s)]

    def _filter_new(self, stocks: list[str], trade_date: str) -> list[str]:
        return [s for s in stocks if not self._is_new_stock(s, trade_date)]

    def _filter_paused(self, stocks: list[str], trade_date: str) -> list[str]:
        out: list[str] = []
        for code in stocks:
            bar = self._bar_on(code, trade_date)
            if bar is not None:
                out.append(code)
        return out

    def _filter_limitup(self, stocks: list[str], trade_date: str) -> list[str]:
        out: list[str] = []
        for code in stocks:
            if code in self.positions:
                out.append(code)
                continue
            bar = self._bar_on(code, trade_date)
            if not bar:
                continue
            pre_close = float(bar.get("pre_close", np.nan))
            close = float(bar.get("close", np.nan))
            if np.isnan(pre_close) or pre_close <= 0:
                continue
            high_limit = round(pre_close * (1 + self._limit_rate(code, self._is_st_name(code))), 2)
            if close < high_limit:
                out.append(code)
        return out

    def _filter_limitdown(self, stocks: list[str], trade_date: str) -> list[str]:
        out: list[str] = []
        for code in stocks:
            if code in self.positions:
                out.append(code)
                continue
            bar = self._bar_on(code, trade_date)
            if not bar:
                continue
            pre_close = float(bar.get("pre_close", np.nan))
            close = float(bar.get("close", np.nan))
            if np.isnan(pre_close) or pre_close <= 0:
                continue
            low_limit = round(pre_close * (1 - self._limit_rate(code, self._is_st_name(code))), 2)
            if close > low_limit:
                out.append(code)
        return out

    def prepare_stock_list(self, previous_date: str) -> None:
        self.hold_list = list(self.positions.keys())
        hl_list: list[str] = []

        for code in self.hold_list:
            bar = self._bar_on(code, previous_date)
            if not bar:
                continue
            close = float(bar.get("close", np.nan))
            pre_close = float(bar.get("pre_close", np.nan))
            if np.isnan(close) or np.isnan(pre_close) or pre_close <= 0:
                continue
            high_limit = round(pre_close * (1 + self._limit_rate(code, self._is_st_name(code))), 2)
            if abs(close - high_limit) <= 0.01:
                hl_list.append(code)

        self.yesterday_hl_list = hl_list

    def _order_target_value(self, ts_code: str, target_value: float, trade_date: str, reason: str) -> bool:
        bar = self._bar_on(ts_code, trade_date)
        if not bar:
            return False

        close = float(bar.get("close", np.nan))
        if np.isnan(close) or close <= 0:
            return False

        if target_value <= 0:
            if ts_code not in self.positions:
                return False
            pos = self.positions[ts_code]
            price = close * (1 - SELL_PRICE_SLIPPAGE)
            turnover = price * pos.volume
            fee = turnover * (CLOSE_COMMISSION + CLOSE_TAX)
            self.cash += turnover - fee
            self.trades.append(
                {
                    "trade_date": trade_date,
                    "ts_code": ts_code,
                    "action": "SELL",
                    "price": price,
                    "volume": pos.volume,
                    "turnover": turnover,
                    "fee": fee,
                    "reason": reason,
                }
            )
            self.positions.pop(ts_code, None)
            return True

        price = close * (1 + BUY_PRICE_SLIPPAGE)
        max_affordable = int(self.cash / (price * (1 + OPEN_COMMISSION)) / MIN_TRADE_VOLUME) * MIN_TRADE_VOLUME
        volume = int(target_value / price / MIN_TRADE_VOLUME) * MIN_TRADE_VOLUME
        volume = min(volume, max_affordable)

        if volume < MIN_TRADE_VOLUME:
            return False

        turnover = price * volume
        fee = turnover * OPEN_COMMISSION
        cost = turnover + fee
        if cost > self.cash:
            return False

        self.cash -= cost
        self.positions[ts_code] = Position(ts_code=ts_code, volume=volume, avg_cost=price)
        self.trades.append(
            {
                "trade_date": trade_date,
                "ts_code": ts_code,
                "action": "BUY",
                "price": price,
                "volume": volume,
                "turnover": turnover,
                "fee": fee,
                "reason": reason,
            }
        )
        return True

    def stop_loss(self, trade_date: str) -> None:
        sold_count = 0

        for code in list(self.yesterday_hl_list):
            if code not in self.positions:
                continue
            bar = self._bar_on(code, trade_date)
            if not bar:
                continue
            close = float(bar.get("close", np.nan))
            pre_close = float(bar.get("pre_close", np.nan))
            if np.isnan(close) or np.isnan(pre_close) or pre_close <= 0:
                continue
            high_limit = round(pre_close * (1 + self._limit_rate(code, self._is_st_name(code))), 2)
            if close < high_limit:
                if self._order_target_value(code, 0, trade_date, reason="yesterday_limit_up_opened"):
                    sold_count += 1

        perf_list: list[tuple[str, float]] = []
        for code in list(self.hold_list):
            if code not in self.positions:
                continue
            bar = self._bar_on(code, trade_date)
            if not bar:
                continue
            pos = self.positions[code]
            close = float(bar.get("close", np.nan))
            if np.isnan(close) or pos.avg_cost <= 0:
                continue
            pnl = (close - pos.avg_cost) / pos.avg_cost
            if pnl < -STOP_LOSS_RATE:
                if self._order_target_value(code, 0, trade_date, reason="hard_stop_loss"):
                    sold_count += 1
            else:
                perf_list.append((code, pnl))

        if sold_count >= 1 and perf_list:
            perf_list.sort(key=lambda x: x[1])
            refill_count = min(3, len(perf_list))
            target_codes = [x[0] for x in perf_list[:refill_count]]
            each_value = self.cash / refill_count if refill_count > 0 else 0
            for code in target_codes:
                self._order_target_value(code, each_value, trade_date, reason="refill_biggest_losers")

    def _calc_lookback_mean(self, ts_codes: list[str], end_date: str) -> float:
        returns: list[float] = []
        for code in ts_codes:
            df = self._load_daily(code)
            if df.empty:
                continue
            part = df[df["trade_date"] <= end_date].tail(LOOKBACK_DAYS)
            if len(part) < 2:
                continue
            first_close = float(part.iloc[0]["close"])
            last_close = float(part.iloc[-1]["close"])
            if first_close <= 0:
                continue
            returns.append((last_close / first_close - 1.0) * 100)
        return float(np.nanmean(returns)) if returns else -999.0

    def _basic_ranked(self, ts_codes: list[str], trade_date: str, ascending: bool) -> list[str]:
        daily_basic = self.client.daily_basic(ts_codes=ts_codes, trade_date=trade_date)
        if daily_basic.empty or "circ_mv" not in daily_basic.columns:
            return []
        daily_basic["circ_mv"] = pd.to_numeric(daily_basic["circ_mv"], errors="coerce")
        daily_basic = daily_basic.dropna(subset=["circ_mv"])
        daily_basic = daily_basic.sort_values("circ_mv", ascending=ascending)
        return daily_basic["ts_code"].drop_duplicates().tolist()[:20]

    def _snapshot(self, ts_codes: list[str], trade_date: str) -> pd.DataFrame:
        base = self.client.daily_basic(ts_codes=ts_codes, trade_date=trade_date)
        if base.empty:
            return pd.DataFrame()

        for col in ["pe", "ps", "pb", "total_mv", "circ_mv", "close"]:
            if col in base.columns:
                base[col] = pd.to_numeric(base[col], errors="coerce")

        # total_mv / circ_mv: 单位万元，转为亿元方便与原策略阈值对应
        if "total_mv" in base.columns:
            base["total_mv_yi"] = base["total_mv"] / 10000
        if "circ_mv" in base.columns:
            base["circ_mv_yi"] = base["circ_mv"] / 10000

        rows: list[dict[str, Any]] = []
        for code in base["ts_code"].dropna().unique().tolist():
            row = {"ts_code": code}
            row.update(self.client.latest_fina_indicator(code, trade_date))
            row.update(self.client.latest_income(code, trade_date))
            row.update(self.client.latest_balance(code, trade_date))
            row.update(self.client.latest_cashflow(code, trade_date))
            rows.append(row)

        extra = pd.DataFrame(rows)
        merged = base.merge(extra, on="ts_code", how="left")

        for col in [
            "roe", "roa", "roic", "netprofit_margin", "grossprofit_margin", "or_yoy", "debt_to_assets",
            "revenue", "oper_cost", "total_profit", "n_income", "non_oper_income", "non_oper_exp",
            "admin_exp", "total_assets", "total_liab", "undistr_porfit", "inventories", "total_share",
            "n_cashflow_act", "ncfps",
        ]:
            if col in merged.columns:
                merged[col] = pd.to_numeric(merged[col], errors="coerce")

        if "total_profit" in merged.columns and "oper_cost" in merged.columns:
            merged["total_profit_to_cost_ratio"] = merged["total_profit"] / merged["oper_cost"].replace(0, np.nan)

        if "oper_cost" in merged.columns and "inventories" in merged.columns:
            merged["inventory_turnover_rate"] = merged["oper_cost"] / merged["inventories"].replace(0, np.nan)

        if "oper_cost" in merged.columns and "revenue" in merged.columns:
            merged["operating_cost_to_revenue_ratio"] = merged["oper_cost"] / merged["revenue"].replace(0, np.nan)

        if "admin_exp" in merged.columns and "revenue" in merged.columns:
            merged["sgai"] = merged["admin_exp"] / merged["revenue"].replace(0, np.nan)

        if "n_income" in merged.columns and "revenue" in merged.columns:
            merged["net_profit_margin_ttm"] = merged["n_income"] / merged["revenue"].replace(0, np.nan)

        if "undistr_porfit" in merged.columns and "total_share" in merged.columns:
            merged["retained_profit_per_share"] = merged["undistr_porfit"] / merged["total_share"].replace(0, np.nan)

        if "ncfps" in merged.columns:
            merged["cashflow_per_share_ttm"] = merged["ncfps"]

        if "non_oper_income" in merged.columns and "non_oper_exp" in merged.columns:
            merged["non_operating_net_profit_ttm"] = merged["non_oper_income"] - merged["non_oper_exp"]

        return merged

    def _small(self, trade_date: str, choice: list[str]) -> list[str]:
        snap = self._snapshot(choice, trade_date)
        if snap.empty:
            return []
        for col in ["roe", "roa", "circ_mv"]:
            if col not in snap.columns:
                snap[col] = np.nan
        cond = (snap["roe"] > 0.15) & (snap["roa"] > 0.10)
        out = snap[cond].sort_values("circ_mv", ascending=True)
        return out["ts_code"].tolist()[: STOCK_NUM * 3]

    def _big(self, trade_date: str, choice: list[str]) -> list[str]:
        snap = self._snapshot(choice, trade_date)
        if snap.empty:
            return []
        for col in ["pe", "ps", "roe", "netprofit_margin", "grossprofit_margin", "or_yoy", "circ_mv"]:
            if col not in snap.columns:
                snap[col] = np.nan

        cond = (
            (snap["pe"] > 0)
            & (snap["pe"] < 30)
            & (snap["ps"] > 0)
            & (snap["ps"] < 8)
            & (snap["roe"] > 0.1)
            & (snap["netprofit_margin"] > 0.1)
            & (snap["grossprofit_margin"] > 0.3)
            & (snap["or_yoy"] > 25)
        )
        out = snap[cond].sort_values("circ_mv", ascending=False)
        return out["ts_code"].tolist()[:STOCK_NUM]

    def _roic_big(self, trade_date: str, choice: list[str]) -> list[str]:
        snap = self._snapshot(choice, trade_date)
        if snap.empty:
            return []
        for col in ["total_mv_yi", "pe", "roa", "debt_to_assets", "or_yoy", "roic", "undistr_porfit"]:
            if col not in snap.columns:
                snap[col] = np.nan

        cond = (
            (snap["total_mv_yi"] > 300)
            & (snap["pe"] > 0)
            & (snap["pe"] < 50)
            & (snap["roa"] > 0.15)
            & (snap["debt_to_assets"] < 50)
            & (snap["or_yoy"] > 20)
            & (snap["roic"] > 0.08)
            & (snap["undistr_porfit"] > 0)
        )
        out = snap[cond].sort_values("undistr_porfit", ascending=False)
        return out["ts_code"].tolist()[:STOCK_NUM]

    def _bm(self, trade_date: str, choice: list[str]) -> list[str]:
        snap = self._snapshot(choice, trade_date)
        if snap.empty:
            return []
        for col in ["total_mv_yi", "pb", "roe", "netprofit_margin", "or_yoy"]:
            if col not in snap.columns:
                snap[col] = np.nan

        cond = (
            (snap["total_mv_yi"] >= 100)
            & (snap["total_mv_yi"] <= 900)
            & (snap["pb"] > 0)
            & (snap["pb"] < 10)
            & (snap["roe"] > 0.2)
            & (snap["netprofit_margin"] > 0.1)
            & (snap["or_yoy"] > 20)
        )
        out = snap[cond].sort_values("total_mv_yi", ascending=True)
        return out["ts_code"].tolist()[:STOCK_NUM]

    def monthly_adjustment(self, trade_date: str, prev_date: str) -> None:
        big_stocks = self.client.index_constituents(BIG_INDEX_CODE, prev_date) or FALLBACK_BIG_POOL
        small_stocks = self.client.index_constituents(SMALL_INDEX_CODE, prev_date) or FALLBACK_SMALL_POOL

        big_stocks = self._filter_new(self._filter_st(self._filter_kcbj(big_stocks)), prev_date)
        small_stocks = self._filter_new(self._filter_st(self._filter_kcbj(small_stocks)), prev_date)

        b_top20 = self._basic_ranked(big_stocks, prev_date, ascending=False)
        s_top20 = self._basic_ranked(small_stocks, prev_date, ascending=True)

        b_mean = self._calc_lookback_mean(b_top20, prev_date)
        s_mean = self._calc_lookback_mean(s_top20, prev_date)

        if b_mean > 10 or s_mean > 10:
            if b_mean > s_mean:
                target_list = list(set(self._roic_big(prev_date, big_stocks) + self._big(prev_date, big_stocks) + self._bm(prev_date, big_stocks)))
            else:
                target_list = self._small(prev_date, small_stocks)
        elif b_mean > s_mean and b_mean > 0:
            target_list = list(set(self._roic_big(prev_date, big_stocks) + self._big(prev_date, big_stocks) + self._bm(prev_date, big_stocks)))
        elif b_mean < s_mean and s_mean > 0:
            target_list = self._small(prev_date, small_stocks)
        else:
            target_list = FOREIGN_ETF

        target_list = self._filter_limitup(target_list, trade_date)
        target_list = self._filter_limitdown(target_list, trade_date)
        target_list = self._filter_paused(target_list, trade_date)

        for code in list(self.hold_list):
            if code not in target_list and code not in self.yesterday_hl_list:
                self._order_target_value(code, 0, trade_date, reason="rebalance_remove")

        position_count = len(self.positions)
        target_num = len(target_list)

        if target_num > position_count:
            to_add = target_num - position_count
            budget = self.cash * CASH_USAGE_RATIO
            each_value = budget / to_add if to_add > 0 else 0
            for code in target_list:
                if code in self.positions:
                    continue
                ok = self._order_target_value(code, each_value, trade_date, reason="rebalance_add")
                if ok and len(self.positions) >= target_num:
                    break

    def _record_equity(self, trade_date: str) -> None:
        market_value = 0.0
        for code, pos in self.positions.items():
            bar = self._bar_on(code, trade_date)
            if not bar:
                continue
            close = float(bar.get("close", np.nan))
            if np.isnan(close) or close <= 0:
                continue
            market_value += close * pos.volume

        total_equity = self.cash + market_value
        self.equity_curve.append(
            {
                "trade_date": trade_date,
                "cash": self.cash,
                "market_value": market_value,
                "equity": total_equity,
                "position_count": len(self.positions),
            }
        )
