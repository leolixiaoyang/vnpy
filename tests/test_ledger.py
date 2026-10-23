from decimal import Decimal

import pandas as pd
import pytest

from quantlab.broker import Broker, FeeModel
from quantlab.data.view import MarketDataView
from quantlab.models import BuyValue, TargetValue, cents
from quantlab.quality import DataError


def test_buy_refill_partial_sell_and_cent_conservation(market):
    broker = Broker(100000, FeeModel(buy_commission=0, sell_commission=0, minimum_commission=0, stock_sell_tax=0))
    symbol = "600000.SH"
    first = broker.execute(BuyValue(symbol, 20000), market, market.asof)
    second = broker.execute(BuyValue(symbol, 10000), market, market.asof)
    pos = broker.snapshot(market.asof).positions[symbol]
    assert pos.quantity == first.quantity + second.quantity
    assert pos.cost_cents == first.turnover_cents + second.turnover_cents
    assert broker.cash_cents + pos.cost_cents == broker.initial_cents
    tomorrow = MarketDataView(market._bundle, "2026-02-03")
    before = broker.snapshot(tomorrow.asof).positions[symbol]
    sold = broker.execute(TargetValue(symbol, before.quantity * before.last_price / 2), tomorrow, tomorrow.asof)
    assert sold.side == "SELL" and sold.quantity < before.quantity
    after = broker.snapshot(tomorrow.asof).positions[symbol]
    assert after.quantity == before.quantity - sold.quantity
    assert broker.cash_cents == broker.initial_cents - before.cost_cents + sold.turnover_cents
    final = broker.execute(TargetValue(symbol, 0), tomorrow, tomorrow.asof)
    assert final.status == "filled" and symbol not in broker.holdings


def test_t1_and_t0_are_security_rules(market):
    broker = Broker(100000)
    broker.execute(BuyValue("600000.SH", 10000), market, market.asof)
    assert broker.execute(TargetValue("600000.SH", 0), market, market.asof).rejection == "settlement_locked"
    tomorrow = MarketDataView(market._bundle, "2026-02-03")
    assert broker.execute(TargetValue("600000.SH", 0), tomorrow, tomorrow.asof).status == "filled"
    t0 = MarketDataView(market._bundle, market.asof, rules={"600000.SH": {"asset_type": "fund", "settlement_days": 0}})
    broker.execute(BuyValue("600000.SH", 10000), t0, t0.asof)
    assert broker.execute(TargetValue("600000.SH", 0), t0, t0.asof).status == "filled"


def test_commission_minimum_tax_and_affordability(market):
    fees = FeeModel()
    assert fees.fee(100000, "BUY", "stock") == 500
    assert fees.fee(100000, "SELL", "stock") == 600
    assert fees.fee(100000, "SELL", "fund") == 500
    broker = Broker(3000, fees)
    r = broker.execute(BuyValue("600000.SH", 999999), market, market.asof)
    assert r.status == "filled" and broker.cash_cents >= 0
    assert broker.cash_cents + r.turnover_cents + r.fee_cents == broker.initial_cents
    tiny = Broker(10)
    assert tiny.execute(BuyValue("600000.SH", 10), market, market.asof).rejection == "insufficient_cash_or_lot"


def test_no_fill_no_cash_and_missing_quote_still_valued(market):
    broker = Broker(100000)
    broker.execute(BuyValue("600000.SH", 10000), market, market.asof)
    initial = broker.cash_cents
    missing = MarketDataView(market._bundle, "2026-02-14")
    assert broker.execute(TargetValue("600000.SH", 0), missing, missing.asof).status == "rejected"
    mark = broker.mark(missing, missing.asof)
    assert mark["market_value"] > 0 and broker.cash_cents == initial
    assert any(e.code == "stale_valuation" for e in missing.quality.events)


def test_price_limit_blocks_and_position_count_cap(market):
    limits = market._bundle.tables["stk_limit"]
    mask = (limits.ts_code == "600000.SH") & (limits.trade_date == market.asof)
    limits.loc[mask, "up_limit"] = market.bar("600000.SH")["close"]
    broker = Broker(100000)
    assert broker.execute(BuyValue("600000.SH", 10000), market, market.asof).rejection == "price_limit"
    assert broker.execute(BuyValue("600036.SH", 10000, max_positions=1), market, market.asof).status == "filled"
    assert broker.execute(BuyValue("000001.SZ", 10000, max_positions=1), market, market.asof).rejection == "position_count_cap"


@pytest.mark.parametrize("value", [-1, float("nan"), float("inf")])
def test_invalid_order_is_error(market, value):
    with pytest.raises(DataError):
        Broker().execute(BuyValue("600000.SH", value), market, market.asof)


def test_corporate_entitlement_survives_sale_and_accrues_before_pay(market):
    broker = Broker(100000, FeeModel(0, 0, 0, 0))
    symbol = "600000.SH"
    buy = broker.execute(BuyValue(symbol, 20000), market, market.asof)
    market._bundle.tables["corporate_actions"] = pd.DataFrame([{
        "ts_code": symbol, "record_date": market.asof, "ex_date": "2026-02-03",
        "pay_date": "2026-02-05", "list_date": "2026-02-04", "cash_per_share": .1, "share_ratio": .1}])
    broker.capture_entitlements(market, market.asof)
    tomorrow = MarketDataView(market._bundle, "2026-02-03")
    broker.corporate_actions(tomorrow, tomorrow.asof)
    assert sum(broker.receivables.values()) == buy.quantity * 10
    pos = broker.snapshot(tomorrow.asof).positions[symbol]
    assert pos.quantity == buy.quantity + int(buy.quantity * .1)
    assert pos.sellable == buy.quantity
    broker.execute(TargetValue(symbol, 0), tomorrow, tomorrow.asof)
    assert broker.snapshot(tomorrow.asof).positions[symbol].quantity == int(buy.quantity * .1)
    broker.corporate_actions(MarketDataView(market._bundle, "2026-02-05"), "2026-02-05")
    assert not broker.receivables


def test_money_rounding():
    assert cents(Decimal("1.005")) == 101
