"""Integer-cent long-only ledger, independent of strategy and data SDKs."""
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from types import MappingProxyType

import numpy as np

from .models import AccountSnapshot, BuyValue, Keep, OrderResult, PositionSnapshot, TargetValue, cents
from .quality import DataError


@dataclass(frozen=True)
class FeeModel:
    buy_commission: float = 0.0003
    sell_commission: float = 0.0003
    minimum_commission: float = 5.0
    stock_sell_tax: float = 0.001
    slippage_bps: float = 0.0

    def __post_init__(self):
        if any(not np.isfinite(x) or x < 0 for x in self.__dict__.values()) or self.slippage_bps >= 10000:
            raise DataError("Fees must be finite and non-negative; slippage below 10000 bps")

    def fee(self, turnover_cents, side, asset_type):
        rate = self.buy_commission if side == "BUY" else self.sell_commission
        commission = max(cents(self.minimum_commission), int((Decimal(turnover_cents) * Decimal(str(rate))).quantize(Decimal("1"), rounding=ROUND_HALF_UP)))
        tax = 0
        if side == "SELL" and asset_type == "stock":
            tax = int((Decimal(turnover_cents) * Decimal(str(self.stock_sell_tax))).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        return commission + tax


@dataclass
class Holding:
    quantity: int = 0
    cost_cents: int = 0
    last_price: float = 0.0
    locked: dict[str, int] = field(default_factory=dict)


class Broker:
    def __init__(self, initial_capital=1_000_000, fees=None):
        if not np.isfinite(initial_capital) or initial_capital <= 0:
            raise DataError("initial_capital must be positive")
        self.cash_cents = cents(initial_capital)
        self.initial_cents = self.cash_cents
        self.fees = fees or FeeModel()
        self.holdings: dict[str, Holding] = {}
        self.orders: list[OrderResult] = []
        self.receivables: dict[str, int] = {}
        self.record_quantities: dict[tuple[str, str], int] = {}
        self.actions: list[dict] = []

    def snapshot(self, day):
        positions = {}
        for symbol, h in self.holdings.items():
            locked = sum(q for unlock, q in h.locked.items() if unlock > day)
            positions[symbol] = PositionSnapshot(symbol, h.quantity, h.quantity - locked, h.cost_cents, h.last_price)
        return AccountSnapshot(self.cash_cents, MappingProxyType(positions))

    def execute(self, intent, market, day):
        symbol = intent.symbol
        def result(status, rejection="", **kwargs):
            r = OrderResult(day, symbol, status, intent.reason, rejection=rejection, **kwargs)
            self.orders.append(r)
            return r
        if isinstance(intent, Keep):
            return result("kept")
        if not np.isfinite(intent.value) or intent.value < 0:
            raise DataError("Order values must be finite and non-negative")
        if isinstance(intent, BuyValue) and intent.max_positions is not None and symbol not in self.holdings and len(self.holdings) >= intent.max_positions:
            return result("rejected", "position_count_cap")
        bar = market.bar(symbol, day)
        if not bar or not np.isfinite(float(bar.get("volume", 1))) or float(bar.get("volume", 1)) <= 0:
            return result("rejected", "no_tradable_bar")
        instrument = market.instrument(symbol)
        h = self.holdings.get(symbol, Holding())
        close = float(bar["close"])
        if isinstance(intent, TargetValue):
            desired = int(intent.value / close / instrument.lot_size) * instrument.lot_size
            quantity = desired - h.quantity
        elif isinstance(intent, BuyValue):
            quantity = int(intent.value / close / instrument.lot_size) * instrument.lot_size
        else:
            raise DataError("Unknown intent type")
        if quantity == 0:
            return result("rejected", "insufficient_cash_or_lot") if isinstance(intent, BuyValue) else result("kept")
        side = "BUY" if quantity > 0 else "SELL"
        up, down = market.limits(symbol, day)
        if not np.isfinite(up) or not np.isfinite(down):
            return result("rejected", "price_limits_unknown", side=side)
        if (side == "BUY" and close >= up - instrument.tick_size / 2) or (side == "SELL" and close <= down + instrument.tick_size / 2):
            return result("rejected", "price_limit", side=side)
        tick = Decimal(str(instrument.tick_size))
        slipped = Decimal(str(close)) * (Decimal("1") + Decimal(str(self.fees.slippage_bps / 10000)) * (1 if side == "BUY" else -1))
        price = float((slipped / tick).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * tick)
        if not down <= price <= up:
            return result("rejected", "slippage_outside_limits", side=side)
        quantity = abs(quantity)
        if side == "SELL":
            quantity = min(quantity, self.snapshot(day).positions[symbol].sellable)
            if quantity == 0:
                return result("rejected", "settlement_locked", side=side)
        else:
            # BuyValue is a cash budget, inclusive of fees. TargetValue describes holding value.
            budget = min(self.cash_cents, cents(intent.value)) if isinstance(intent, BuyValue) else self.cash_cents
            max_qty = int(budget / 100 / price / instrument.lot_size) * instrument.lot_size
            quantity = min(quantity, max_qty)
            while quantity > 0:
                turnover = cents(Decimal(str(price)) * quantity)
                if turnover + self.fees.fee(turnover, side, instrument.asset_type) <= budget:
                    break
                quantity -= instrument.lot_size
            if quantity <= 0:
                return result("rejected", "insufficient_cash_or_lot", side=side)
        turnover = cents(Decimal(str(price)) * quantity)
        fee = self.fees.fee(turnover, side, instrument.asset_type)
        if side == "BUY":
            self.cash_cents -= turnover + fee
            h.quantity += quantity
            h.cost_cents += turnover + fee
            if instrument.settlement_days:
                # T+1 means next exchange session; ISO next calendar day is sufficient to
                # prevent same-session sales (there are no weekend replay sessions).
                from datetime import date, timedelta
                unlock = (date.fromisoformat(day) + timedelta(days=instrument.settlement_days)).isoformat()
                h.locked[unlock] = h.locked.get(unlock, 0) + quantity
            self.holdings[symbol] = h
        else:
            self.cash_cents += turnover - fee
            sold_cost = int((Decimal(h.cost_cents) * quantity / h.quantity).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
            h.cost_cents -= sold_cost
            h.quantity -= quantity
            if not h.quantity:
                self.holdings.pop(symbol)
        h.last_price = close
        if self.cash_cents < 0 or h.quantity < 0 or h.cost_cents < 0:
            raise DataError("Ledger invariant violated")
        return result("filled", side=side, quantity=quantity, price=price, fee_cents=fee, turnover_cents=turnover)

    def mark(self, market, day):
        value = 0
        for symbol, h in self.holdings.items():
            bar = market.bar(symbol, day)
            if bar:
                h.last_price = float(bar["close"])
            else:
                market.quality.record("stale_valuation", f"{symbol} {day}")
            value += cents(Decimal(str(h.last_price)) * h.quantity)
        receivables = sum(self.receivables.values())
        equity = self.cash_cents + value + receivables
        return {"trade_date": day, "cash": self.cash_cents / 100, "market_value": value / 100,
                "receivables": receivables / 100, "equity": equity / 100, "position_count": len(self.holdings)}

    def corporate_actions(self, market, day):
        """Normalized entitlements: ex-date accrual, pay-date cash, listing-date shares."""
        actions = market._bundle.table("corporate_actions")
        for key, amount in list(self.receivables.items()):
            if key.split("|")[0] <= day:
                self.cash_cents += amount
                self.receivables.pop(key)
        if actions.empty:
            return
        for i, row in actions[actions.ex_date == day].iterrows():
            symbol = row.ts_code
            if not isinstance(row.get("ann_date"), str) or row.ann_date >= day:
                market.quality.record("corporate_action_notice_unverified", f"{symbol} {day}")
            quantity = self.record_quantities.get((symbol, row.record_date), 0)
            if row.record_date == day:
                market.quality.record("same_day_record_ex_approximation", f"{symbol} {day}: use day-start quantity")
                quantity = self.holdings.get(symbol, Holding()).quantity
            if not quantity:
                continue
            cash = cents(Decimal(str(row.get("cash_per_share", 0))) * quantity)
            pay_date = row.get("pay_date")
            if not isinstance(pay_date, str):
                market.quality.record("dividend_pay_date_proxy", symbol)
                pay_date = day
            if pay_date <= day:
                self.cash_cents += cash
            else:
                self.receivables[f"{pay_date}|{symbol}|{i}"] = cash
            ratio = float(row.get("share_ratio", 0))
            extra = int(quantity * ratio)
            if quantity * ratio != extra:
                market.quality.record("fractional_bonus_shares", symbol)
            if extra:
                h = self.holdings.setdefault(symbol, Holding())
                h.quantity += extra
                listing = row.get("list_date")
                if not isinstance(listing, str):
                    market.quality.record("bonus_listing_date_proxy", symbol)
                    listing = day
                h.locked[listing] = h.locked.get(listing, 0) + extra
            self.actions.append({"date": day, "symbol": symbol, "cash_cents": cash, "bonus_shares": extra})

    def capture_entitlements(self, market, day):
        actions = market._bundle.table("corporate_actions")
        if not actions.empty:
            for _, row in actions[actions.record_date == day].iterrows():
                self.record_quantities[(row.ts_code, day)] = self.holdings.get(row.ts_code, Holding()).quantity
