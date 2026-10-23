from dataclasses import replace

import pandas as pd
import pytest

from quantlab.backtest import BacktestRunner
from quantlab.broker import Broker, FeeModel
from quantlab.data.view import MarketDataView
from quantlab.models import BuyValue, Context, OrderResult
from quantlab.strategies.all_weather_rotation import AllWeatherRotation


@pytest.mark.parametrize("big,small,want", [(12, 11, "big"), (11, 12, "small"), (12, 12, "small"),
    (3, 2, "big"), (2, 3, "small"), (2, 2, "funds"), (-1, -2, "funds"), (0, 0, "funds")])
def test_regime_boundaries(big, small, want):
    assert AllWeatherRotation.regime(big, small) == want


def context(market, broker=None):
    broker = broker or Broker()
    snap = broker.snapshot(market.asof)
    return Context(market.asof, "2026-01-30", True, market, snap, snap)


def test_small_cap_total_market_value_not_circulating(market):
    ctx = context(market)
    frame = pd.DataFrame([{"ts_code": "A", "roe_pct": .16, "roa_pct": .11, "total_mv": 20, "circ_mv": 1},
                          {"ts_code": "B", "roe_pct": .16, "roa_pct": .11, "total_mv": 10, "circ_mv": 9},
                          {"ts_code": "C", "roe_pct": .15, "roa_pct": .11, "total_mv": 1, "circ_mv": 1}])
    selected = AllWeatherRotation()._select(frame, [("roe_pct", "gt", .15), ("roa_pct", "gt", .1)], "total_mv", True, 9, ctx)
    assert selected == ["B", "A"]


def test_month_middle_not_immediately_invested_and_repeatable(bundle):
    first = BacktestRunner(bundle, AllWeatherRotation()).run("2026-01-15", "2026-02-10")
    second = BacktestRunner(bundle, AllWeatherRotation()).run("2026-01-15", "2026-02-10")
    pd.testing.assert_frame_equal(first.equity, second.equity)
    pd.testing.assert_frame_equal(first.trades, second.trades)
    assert not first.trades.empty
    assert first.trades.date.min() == "2026-02-02"
    assert (first.equity[first.equity.trade_date < "2026-02-02"].equity == 1000000).all()
    assert "hard_stop_loss" in set(first.trades.reason)
    assert "refill_biggest_losers" in set(first.trades.reason)


def test_failed_exit_no_refill_and_fixed_thirds(market):
    broker = Broker(100000, FeeModel(0, 0, 0, 0))
    broker.execute(BuyValue("600000.SH", 10000), market, market.asof)
    broker.execute(BuyValue("600036.SH", 10000), market, market.asof)
    ctx = context(market, broker)
    strategy = AllWeatherRotation()
    failed = (OrderResult(ctx.date, "000001.SZ", "rejected", "hard_stop_loss", side="SELL"),)
    assert strategy.on_phase("refill", ctx, failed) == []
    sold = (OrderResult(ctx.date, "000001.SZ", "filled", "hard_stop_loss", side="SELL", quantity=100),)
    intents = strategy.on_phase("refill", ctx, sold)
    assert len(intents) == 2 and len({i.symbol for i in intents}) == 2
    assert all(i.value == pytest.approx(ctx.account.cash / 3) for i in intents)


def test_invalid_strength_keeps_positions_instead_of_fund_fallback(market):
    strategy = AllWeatherRotation()
    market._bundle.tables["daily_basic"] = pd.DataFrame()
    ctx = context(market)
    assert strategy.on_phase("rebalance_exit", ctx, ()) == []
    assert strategy.on_phase("rebalance_entry", ctx, ()) == []
    assert strategy.decisions[-1]["regime"] == "no_rebalance"


def test_retained_limit_up_outsider_and_original_position_count(market):
    broker = Broker(100000, FeeModel(0, 0, 0, 0))
    broker.execute(BuyValue("600000.SH", 10000), market, market.asof)
    ctx = context(market, broker)
    strategy = AllWeatherRotation()
    strategy.targets = ["600036.SH", "000001.SZ", "000002.SZ"]
    intents = strategy.on_phase("rebalance_entry", ctx, ())
    assert len(intents) == 3  # Later candidates may replace rejected earlier orders.
    assert all(i.value == pytest.approx(ctx.account.cash / 2) for i in intents)
    filled = [broker.execute(i, market, market.asof) for i in intents]
    assert len(broker.holdings) == 3
    assert filled[-1].rejection == "position_count_cap"


def test_simple_strategy_without_core_changes(bundle):
    class Simple:
        name = "one_shot"
        def on_phase(self, phase, context, results):
            return [BuyValue("600000.SH", 10000)] if phase == "rebalance_entry" and not context.account.positions else []
    result = BacktestRunner(bundle, Simple()).run("2026-01-15", "2026-01-20")
    assert len(result.trades) == 1
