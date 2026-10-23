from dataclasses import asdict

import pandas as pd

from .broker import Broker
from .data.view import MarketDataView
from .models import Context
from .quality import DataError, QualityLog
from .reports import BacktestResult


class BacktestRunner:
    def __init__(self, bundle, strategy, initial_capital=1_000_000, fees=None,
                 strict=False, instrument_rules=None, fallback_pools=None, benchmark="000300.SH"):
        self.bundle, self.strategy = bundle, strategy
        self.quality = QualityLog(strict)
        self.broker = Broker(initial_capital, fees)
        self.rules, self.pools, self.benchmark = instrument_rules, fallback_pools, benchmark

    def run(self, start, end):
        if start > end:
            raise DataError("start must not follow end")
        self.bundle.preflight(start, end, self.quality)
        calendar = self.bundle.table("trade_cal")
        sessions = sorted(calendar[calendar.is_open == 1].cal_date.unique())
        equity, positions, benchmarks = [], [], []
        for i, day in enumerate(sessions):
            if not start <= day <= end:
                continue
            if i == 0:
                raise DataError("A prior trading session is required")
            prev = sessions[i - 1]
            market = MarketDataView(self.bundle, day, self.quality, self.rules, self.pools)
            if not benchmarks:
                prior = market.bar(self.benchmark, prev)
                benchmarks.append({"trade_date": prev, "close": prior["close"] if prior else None})
                if not prior:
                    self.quality.record("missing_benchmark", f"{self.benchmark} {prev}")
            self.broker.corporate_actions(market, day)
            day_start = self.broker.snapshot(day)
            results = []
            first = day[:7] != prev[:7]
            for phase in ["rebalance_exit", "rebalance_entry", "risk_exit", "refill"]:
                ctx = Context(day, prev, first, market, self.broker.snapshot(day), day_start)
                intents = self.strategy.on_phase(phase, ctx, tuple(results))
                for intent in intents:
                    results.append(self.broker.execute(intent, market, day))
            equity.append(self.broker.mark(market, day))
            self.broker.capture_entitlements(market, day)
            for symbol, pos in self.broker.snapshot(day).positions.items():
                positions.append({"trade_date": day, **asdict(pos)})
            bar = market.bar(self.benchmark, day)
            benchmarks.append({"trade_date": day, "close": bar["close"] if bar else None})
            if not bar:
                self.quality.record("missing_benchmark", f"{self.benchmark} {day}")
        return BacktestResult(
            pd.DataFrame(equity), pd.DataFrame([asdict(r) for r in self.broker.orders]),
            pd.DataFrame(positions), pd.DataFrame(benchmarks), self.broker.initial_cents / 100,
            {"execution_model": "same_day_close_signal_and_fill; optimistic daily approximation",
             "benchmark": self.benchmark, "data": self.bundle.metadata,
             "strategy": self.strategy.name, "fees": asdict(self.broker.fees),
             "quality": self.quality.export(), "corporate_actions": self.broker.actions,
             "decisions": getattr(self.strategy, "decisions", [])})
