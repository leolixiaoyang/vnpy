from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Mapping, Protocol, TYPE_CHECKING

if TYPE_CHECKING:
    from .data.view import MarketDataView


def cents(value: float | Decimal) -> int:
    return int((Decimal(str(value)) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


@dataclass(frozen=True)
class Instrument:
    symbol: str
    asset_type: str = "stock"
    lot_size: int = 100
    settlement_days: int = 1
    tick_size: float = 0.01

    def __post_init__(self):
        import math
        if self.asset_type not in {"stock", "fund"} or self.lot_size <= 0 or self.settlement_days not in {0, 1} or not math.isfinite(self.tick_size) or self.tick_size <= 0:
            raise ValueError("Invalid instrument type, lot, T+0/T+1 settlement or tick")


@dataclass(frozen=True)
class PositionSnapshot:
    symbol: str
    quantity: int
    sellable: int
    cost_cents: int
    last_price: float

    @property
    def avg_cost(self) -> float:
        return self.cost_cents / 100 / self.quantity if self.quantity else 0.0


@dataclass(frozen=True)
class AccountSnapshot:
    cash_cents: int
    positions: Mapping[str, PositionSnapshot]

    @property
    def cash(self):
        return self.cash_cents / 100


@dataclass(frozen=True)
class TargetValue:
    symbol: str
    value: float
    reason: str = "target"


@dataclass(frozen=True)
class BuyValue:
    symbol: str
    value: float
    reason: str = "buy"
    max_positions: int | None = None


@dataclass(frozen=True)
class Keep:
    symbol: str
    reason: str = "keep"


Intent = TargetValue | BuyValue | Keep


@dataclass(frozen=True)
class OrderResult:
    date: str
    symbol: str
    status: str
    reason: str
    side: str = ""
    quantity: int = 0
    price: float = 0.0
    fee_cents: int = 0
    turnover_cents: int = 0
    rejection: str = ""


@dataclass(frozen=True)
class Context:
    date: str
    previous_date: str
    first_session_of_month: bool
    market: "MarketDataView"
    account: AccountSnapshot
    day_start: AccountSnapshot


class Strategy(Protocol):
    """Ordered phases react to actual preceding fills, not hypothetical cash."""
    name: str

    def on_phase(self, phase: str, context: Context, results: tuple[OrderResult, ...]) -> list[Intent]: ...
