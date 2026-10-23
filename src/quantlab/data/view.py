"""Date-bounded normalized data. Never lets a strategy see future rows."""
from datetime import date

import numpy as np
import pandas as pd

from ..models import Instrument
from ..quality import DataError, QualityLog


def number(row, name, default=np.nan):
    value = row.get(name, default)
    return float(value) if pd.notna(value) else default


class MarketDataView:
    def __init__(self, bundle, asof: str, quality=None, rules=None, fallback_pools=None):
        self._bundle, self.asof = bundle, asof
        self.quality = quality if quality is not None else QualityLog()
        self.rules = rules or {}
        self.fallback_pools = fallback_pools or {}

    def _date(self, value=None):
        value = value or self.asof
        if value > self.asof:
            raise DataError(f"Future data access {value} > {self.asof}")
        return value

    def valuations(self, symbols, day=None):
        day = self._date(day)
        df = self._bundle.table("daily_basic")
        if df.empty:
            return df
        return df[(df.trade_date == day) & df.ts_code.isin(symbols)].copy()

    def bars(self, symbol, end=None, count=None, adjusted=False):
        end = self._date(end)
        frames = []
        for api in ["daily", "fund_daily", "index_daily"]:
            df = self._bundle.table(api)
            if not df.empty:
                frames.append(df[(df.ts_code == symbol) & (df.trade_date <= end)])
        if not frames:
            return pd.DataFrame()
        df = pd.concat(frames).sort_values("trade_date").drop_duplicates("trade_date")
        if adjusted and not df.empty:
            factors = self._bundle.table("fund_adj" if self.is_fund(symbol) else "adj_factor")
            if factors.empty:
                self.quality.record("unadjusted_signal", symbol)
            else:
                fs = factors[(factors.ts_code == symbol) & (factors.trade_date <= end)]
                df = df.merge(fs[["trade_date", "adj_factor"]], on="trade_date", how="left")
                if df.adj_factor.isna().any():
                    self.quality.record("missing_adjustment", symbol)
                    # Never mix adjusted and raw prices within a return window.
                else:
                    df["close"] = df.close * df.adj_factor
        return df.tail(count).copy() if count else df.copy()

    def bar(self, symbol, day=None):
        day = self._date(day)
        df = self.bars(symbol, day, 1)
        if df.empty or df.iloc[-1].trade_date != day:
            return None
        row = df.iloc[-1].to_dict()
        return row if np.isfinite(number(row, "close")) and number(row, "close") > 0 else None

    def is_fund(self, symbol):
        if self.rules.get(symbol, {}).get("asset_type") == "fund":
            return True
        df = self._bundle.table("fund_basic")
        return not df.empty and bool((df.ts_code == symbol).any())

    def instrument(self, symbol):
        explicit = self.rules.get(symbol)
        if explicit:
            values = dict(explicit)
            verified = values.pop("settlement_verified", False)
            if values.get("asset_type") == "fund" and not verified:
                self.quality.record("fund_settlement_unverified", symbol)
            return Instrument(symbol, **values)
        stocks = self._bundle.table("stock_basic")
        if not stocks.empty and (stocks.ts_code == symbol).any():
            return Instrument(symbol)
        if self.is_fund(symbol):
            self.quality.record("fund_rule_t1", symbol)
            return Instrument(symbol, "fund", tick_size=0.001)
        raise DataError(f"Unknown instrument type: {symbol}")

    def limits(self, symbol, day=None):
        day = self._date(day)
        df = self._bundle.table("stk_limit")
        if not df.empty:
            found = df[(df.ts_code == symbol) & (df.trade_date == day)]
            if not found.empty:
                row = found.iloc[-1]
                if pd.notna(row.up_limit) and pd.notna(row.down_limit):
                    return float(row.up_limit), float(row.down_limit)
        bar = self.bar(symbol, day)
        if not bar:
            return np.nan, np.nan
        self.quality.record("estimated_price_limits", f"{symbol} {day}")
        pre = number(bar, "pre_close")
        if not np.isfinite(pre) or pre <= 0:
            return np.nan, np.nan
        ins = self.instrument(symbol)
        if ins.asset_type == "fund":
            rate = 0.1  # Explicitly labelled approximation, not inferred T+0 eligibility.
        elif symbol.endswith(".BJ"):
            rate = 0.3
        elif symbol.startswith(("688", "689")) or (symbol.startswith(("300", "301")) and day >= "2020-08-24"):
            rate = 0.2
        else:
            rate = 0.05 if self.is_st(symbol, day) else 0.1
        from decimal import Decimal, ROUND_HALF_UP
        def rounded(value):
            tick = Decimal(str(ins.tick_size))
            return float((Decimal(str(value)) / tick).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * tick)
        return rounded(pre * (1 + rate)), rounded(pre * (1 - rate))

    def is_st(self, symbol, day=None):
        day = self._date(day)
        names = self._bundle.table("namechange")
        if not names.empty:
            rows = names[(names.ts_code == symbol) & (names.start_date <= day)]
            if "ann_date" in rows:
                rows = rows[rows.ann_date.isna() | (rows.ann_date < day)]
            if not rows.empty:
                row = rows.sort_values("start_date").iloc[-1]
                if pd.isna(row.get("end_date")) or row.end_date >= day:
                    return any(tag in str(row["name"]) for tag in ["ST", "*", "退"])
        self.quality.record("current_name_for_history", symbol)
        basic = self._bundle.table("stock_basic")
        rows = basic[basic.ts_code == symbol] if not basic.empty else basic
        return not rows.empty and any(tag in str(rows.iloc[-1].get("name", "")) for tag in ["ST", "*", "退"])

    def constituents(self, index, day=None):
        day = self._date(day)
        df = self._bundle.table("index_weight")
        if not df.empty:
            rows = df[(df.index_code == index) & (df.trade_date <= day)]
            if not rows.empty:
                latest = rows.trade_date.max()
                self.quality.record("monthly_constituent_snapshot", f"{index} at {day} uses {latest}")
                return sorted(rows[rows.trade_date == latest].con_code.unique())
        self.quality.record("fallback_constituents", f"{index} {day}")
        return list(self.fallback_pools.get(index, []))

    def eligible(self, symbols, day, min_listing_days=375):
        day = self._date(day)
        basic = self._bundle.table("stock_basic")
        out = []
        for symbol in sorted(set(symbols)):
            if symbol.startswith(("3", "4", "8", "68", "92")) or symbol.endswith(".BJ"):
                continue
            row = basic[basic.ts_code == symbol] if not basic.empty else basic
            if row.empty or pd.isna(row.iloc[-1].get("list_date")):
                self.quality.record("missing_listing_date", symbol)
                continue
            info = row.iloc[-1]
            if (date.fromisoformat(day) - date.fromisoformat(info.list_date)).days < min_listing_days:
                continue
            if pd.notna(info.get("delist_date")) and info.delist_date <= day:
                continue
            if not self.is_st(symbol, day):
                out.append(symbol)
        return out

    def financial_rows(self, api, symbol, day):
        day = self._date(day)
        df = self._bundle.table(api)
        if df.empty:
            return df
        rows = df[df.ts_code == symbol].copy()
        if "f_ann_date" in rows:
            rows["available"] = rows.f_ann_date.fillna(rows.ann_date)
        else:
            rows["available"] = rows.ann_date
        rows = rows[(rows.available < day) & (rows.end_date <= day)]
        if "report_type" in rows:
            rows = rows[rows.report_type.astype(str).isin(["1", "1.0"])]
        if rows.empty:
            return rows
        rows = rows.sort_values(["end_date", "available"])
        # Different revisions with the same publication date cannot be chronologically resolved.
        if rows.duplicated(["end_date", "available"]).any():
            raise DataError(f"{api}: ambiguous financial revisions for {symbol}")
        self.quality.record("revision_history_unverified", f"{api} {symbol}")
        return rows.drop_duplicates("end_date", keep="last")

    @staticmethod
    def ttm(rows, field):
        if rows.empty or field not in rows:
            return np.nan
        latest = rows.iloc[-1]
        period = latest.end_date
        value = number(latest, field)
        if period.endswith("12-31"):
            return value
        previous_year = int(period[:4]) - 1
        prev = rows[rows.end_date == f"{previous_year}{period[4:]}"]
        annual = rows[rows.end_date == f"{previous_year}-12-31"]
        if prev.empty or annual.empty:
            return np.nan
        return value + number(annual.iloc[-1], field) - number(prev.iloc[-1], field)

    def fundamentals(self, symbols, day=None):
        day = self._date(day)
        basic = self._bundle.table("daily_basic")
        output = []
        for symbol in sorted(set(symbols)):
            rows = basic[(basic.ts_code == symbol) & (basic.trade_date == day)] if not basic.empty else basic
            if rows.empty:
                self.quality.record("missing_valuation", f"{symbol} {day}")
                continue
            r = rows.iloc[-1].to_dict()
            fin = self.financial_rows("fina_indicator", symbol, day)
            balance = self.financial_rows("balancesheet", symbol, day)
            cash = self.financial_rows("cashflow", symbol, day)
            f = fin.iloc[-1] if not fin.empty else {}
            b = balance.iloc[-1] if not balance.empty else {}
            mapping = {"eps_single": ("q_eps", "eps"), "roe_pct": ("q_roe", "roe"),
                       "roa_pct": ("q_npta", "npta"), "net_margin_pct": ("q_netprofit_margin", "netprofit_margin"),
                       "gross_margin_pct": ("q_gsprofit_margin", "grossprofit_margin"),
                       "revenue_growth_pct": ("q_sales_yoy", "or_yoy"),
                       "total_revenue_growth_pct": ("q_gr_yoy", "tr_yoy"),
                       "op_growth_pct": ("q_op_yoy", "op_yoy")}
            for name, (quarter, cumulative) in mapping.items():
                r[name] = number(f, quarter)
                if not np.isfinite(r[name]):
                    r[name] = number(f, cumulative)
                    if np.isfinite(r[name]):
                        self.quality.record("cumulative_metric_proxy", f"{symbol}: {name} <- {cumulative}")
            # Same conceptual quarterly metrics can still differ between vendors' formulas.
            self.quality.record("cross_vendor_financial_formula", symbol)
            r["retained_profit"] = number(b, "undistr_porfit")
            equity = number(b, "total_hldr_eqy_inc_min_int")
            r["liability_equity"] = number(b, "total_liab") / equity if np.isfinite(equity) and equity != 0 else np.nan
            netcash = self.ttm(cash, "n_incr_cash_cash_equ")
            r["pcf_net_ttm"] = number(r, "total_mv") / netcash if np.isfinite(netcash) and netcash != 0 else np.nan
            r["roic_ttm_ratio"] = number(f, "roic") / 100
            if np.isfinite(r["roic_ttm_ratio"]):
                self.quality.record("roic_ttm_proxy", f"{symbol}: reported roic/100, not JoinQuant roic_ttm")
            output.append(r)
        return pd.DataFrame(output)
