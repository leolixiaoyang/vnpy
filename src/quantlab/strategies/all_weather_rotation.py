from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..models import BuyValue, TargetValue


@dataclass(frozen=True)
class Parameters:
    stock_num: int = 3
    lookback: int = 10
    min_listing_days: int = 375
    stop_loss: float = 0.08
    big_index: str = "000300.SH"
    small_index: str = "399101.SZ"
    funds: tuple[str, ...] = ("518880.SH", "513030.SH", "513100.SH", "164824.SZ", "159866.SZ")


class AllWeatherRotation:
    name = "all_weather_rotation"

    def __init__(self, **kwargs):
        self.params = Parameters(**kwargs)
        if self.params.stock_num < 1 or self.params.lookback < 2 or not 0 < self.params.stop_loss < 1:
            raise ValueError("Invalid strategy parameters")
        self.decisions = []
        self.targets = []
        self.limit_held = set()

    def _select(self, df, rules, sort, ascending, count, ctx):
        if df.empty:
            return []
        candidates = df.copy()
        for col, op, value in rules:
            series = pd.to_numeric(candidates[col], errors="coerce") if col in candidates else pd.Series(np.nan, index=candidates.index)
            missing = series.isna()
            if missing.any():
                ctx.market.quality.record("skipped_financial_filter", f"{ctx.date} {col}: {','.join(candidates.loc[missing, 'ts_code'])}")
            if op == "gt":
                passed = series > value
            elif op == "lt":
                passed = series < value
            else:
                passed = series.between(*value)
            candidates = candidates[passed | missing]
        if sort not in candidates or candidates[sort].isna().any():
            ctx.market.quality.record("missing_ranking_metric", f"{ctx.date} {sort}")
            if sort not in candidates:
                return []
            candidates = candidates.dropna(subset=[sort])
        return candidates.sort_values([sort, "ts_code"], ascending=[ascending, True]).head(count).ts_code.tolist()

    def _strong(self, pool, ascending, ctx):
        df = ctx.market.valuations(pool, ctx.previous_date)
        if df.empty:
            return None
        df = df[(df.trade_date == ctx.previous_date) & df.ts_code.isin(pool)].dropna(subset=["circ_mv"])
        codes = df.sort_values(["circ_mv", "ts_code"], ascending=[ascending, True]).head(20).ts_code.tolist()
        returns, valid = [], 0
        for symbol in codes:
            bars = ctx.market.bars(symbol, ctx.previous_date, self.params.lookback, adjusted=True)
            if len(bars) < self.params.lookback or float(bars.iloc[0].close) <= 0:
                ctx.market.quality.record("strength_return_zero_fill", f"{ctx.date} {symbol}")
                returns.append(0.0)
            else:
                value = (float(bars.iloc[-1].close) / float(bars.iloc[0].close) - 1) * 100
                if np.isfinite(value):
                    valid += 1
                    returns.append(value)
                else:
                    returns.append(0.0)
        return float(np.mean(returns)) if returns and valid else None

    @staticmethod
    def regime(big, small):
        if big > 10 or small > 10:
            return "big" if big > small else "small"
        if big > small and big > 0:
            return "big"
        if small > big and small > 0:
            return "small"
        return "funds"

    def _targets(self, ctx):
        p, m = self.params, ctx.market
        big = m.eligible(m.constituents(p.big_index, ctx.previous_date), ctx.previous_date, p.min_listing_days)
        small = m.eligible(m.constituents(p.small_index, ctx.previous_date), ctx.previous_date, p.min_listing_days)
        b, s = self._strong(big, False, ctx), self._strong(small, True, ctx)
        if b is None or s is None:
            m.quality.record("invalid_strength_no_rebalance", ctx.date)
            self.decisions.append({"date": ctx.date, "regime": "no_rebalance", "big": b, "small": s})
            return None
        regime = self.regime(b, s)
        if regime == "funds":
            targets = list(p.funds)
        else:
            df = m.fundamentals(big if regime == "big" else small, ctx.previous_date)
            select = lambda rules, sort, asc, count: self._select(df, rules, sort, asc, count, ctx)
            if regime == "small":
                targets = select([("roe_pct", "gt", .15), ("roa_pct", "gt", .10)], "total_mv", True, p.stock_num * 3)
            else:
                roic = select([("total_mv", "gt", 300e8), ("pe_ttm", "between", (0, 50)),
                    ("eps_single", "gt", .12), ("roa_pct", "gt", .15), ("liability_equity", "lt", .5),
                    ("total_revenue_growth_pct", "gt", .3), ("revenue_growth_pct", "gt", .2),
                    ("retained_profit", "gt", 0), ("roic_ttm_ratio", "gt", .08)], "retained_profit", False, p.stock_num)
                large = select([("pe", "between", (0, 30)), ("ps_ttm", "between", (0, 8)), ("pcf_net_ttm", "lt", 10),
                    ("eps_single", "gt", .3), ("roe_pct", "gt", .1), ("net_margin_pct", "gt", .1),
                    ("gross_margin_pct", "gt", .3), ("revenue_growth_pct", "gt", .25)], "total_mv", False, p.stock_num)
                bm = select([("total_mv", "between", (100e8, 900e8)), ("pb", "between", (0, 10)),
                    ("pcf_net_ttm", "lt", 4), ("eps_single", "gt", .3), ("roe_pct", "gt", .2),
                    ("net_margin_pct", "gt", .1), ("revenue_growth_pct", "gt", .2),
                    ("op_growth_pct", "gt", .1)], "total_mv", True, p.stock_num)
                targets = list(dict.fromkeys((bm + roic + large) if b > 10 or s > 10 else (roic + large + bm)))
        out = []
        for symbol in targets:
            bar = m.bar(symbol)
            if not bar or float(bar.get("volume", 1)) <= 0:
                continue
            up, down = m.limits(symbol)
            if symbol in ctx.account.positions or down < bar["close"] < up:
                out.append(symbol)
        self.decisions.append({"date": ctx.date, "regime": regime, "big": b, "small": s, "targets": out})
        return out

    def on_phase(self, phase, ctx, results):
        if phase == "rebalance_exit":
            self.targets = None
            self.limit_held = set()
            for symbol in ctx.day_start.positions:
                bar = ctx.market.bar(symbol, ctx.previous_date)
                up, _ = ctx.market.limits(symbol, ctx.previous_date)
                if bar and np.isfinite(up) and bar["close"] >= up - .00001:
                    self.limit_held.add(symbol)
            if ctx.first_session_of_month:
                self.targets = self._targets(ctx)
            if self.targets is None:
                return []
            return [TargetValue(s, 0, "rebalance_remove") for s in ctx.day_start.positions if s not in self.targets and s not in self.limit_held]
        if phase == "rebalance_entry":
            if self.targets is None or len(self.targets) <= len(ctx.account.positions):
                return []
            remaining = len(self.targets) - len(ctx.account.positions)
            each = ctx.account.cash / remaining
            # Keep the original position-count cap even with retained non-target limit-up holdings.
            new = [s for s in self.targets if s not in ctx.account.positions]
            return [BuyValue(s, each, "rebalance_add", max_positions=len(self.targets)) for s in new]
        if phase == "risk_exit":
            orders = []
            for symbol in ctx.day_start.positions:
                if symbol not in ctx.account.positions:
                    continue
                bar = ctx.market.bar(symbol)
                if not bar:
                    continue
                up, _ = ctx.market.limits(symbol)
                if symbol in self.limit_held and bar["close"] < up:
                    orders.append(TargetValue(symbol, 0, "yesterday_limit_up_opened"))
                elif bar["close"] < ctx.account.positions[symbol].avg_cost * (1 - self.params.stop_loss):
                    orders.append(TargetValue(symbol, 0, "hard_stop_loss"))
            return orders
        if phase == "refill":
            if not any(r.status == "filled" and r.side == "SELL" and r.reason in {"hard_stop_loss", "yesterday_limit_up_opened"} for r in results):
                return []
            candidates = []
            for symbol in ctx.day_start.positions:
                if symbol not in ctx.account.positions:
                    continue
                pos = ctx.account.positions[symbol]
                bar = ctx.market.bar(symbol)
                if bar and pos.avg_cost > 0:
                    pnl = bar["close"] / pos.avg_cost - 1
                    # A blocked stop-loss remains excluded from the original survivors list.
                    if pnl >= -self.params.stop_loss:
                        candidates.append((pnl, symbol))
            return [BuyValue(s, ctx.account.cash / 3, "refill_biggest_losers") for _, s in sorted(candidates)[:3]]
        return []
