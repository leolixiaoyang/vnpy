# Developing a strategy

The installed `quantlab-research` distribution contains only `quantlab`; legacy scripts and reference notebooks are not runtime dependencies. Build with `python -m build --wheel`, install the wheel in a fresh environment and run outside the source directory.

## Interfaces and data flow

`AKShareTransport.query` or `SDKTransport.query` → shared `TushareProvider` table-contract layer → normalized `DataBundle` → bounded `MarketDataView` → strategy intents → `Broker` → `BacktestResult`. The shared class name denotes the table schema, not a service dependency. Provider construction is centralized in `quantlab.data.factory`; the default is AKShare, selected through `data.provider` or the preparation/doctor `--provider` override.

DataBundle tables are normalized (yuan, individual shares, ISO dates). Do not normalize a frozen table twice. Snapshot manifests contain raw-file hashes and normalization/mapping versions. Backtests read snapshots only; network preparation is explicit. Quality events travel with snapshots into experiments.

```python
from quantlab.models import BuyValue

class MyStrategy:
    name = "my_strategy"

    def on_phase(self, phase, context, results):
        if phase == "rebalance_entry" and not context.account.positions:
            bar = context.market.bar("600000.SH")
            if bar:
                return [BuyValue("600000.SH", context.account.cash / 2, "initial_buy")]
        return []
```

Put an importable module on the normal Python import path and configure:

```toml
[strategy]
factory = "my_package.my_strategy:MyStrategy"
```

No broker or report changes are needed. Strategies must implement deterministic iteration and own their state. Create a fresh strategy and runner for each experiment; a runner is a single-use account simulation.

## Four ordered phases

1. `rebalance_exit`: daily initialization and optional monthly exit intents.
2. `rebalance_entry`: account includes actual preceding exit fills.
3. `risk_exit`: account includes monthly additions, while `day_start` remains the original snapshot.
4. `refill`: `results` contains actual orders from earlier phases that day.

`Context` exposes date, previous session, month boundary, market, current account and day-start account. Account snapshots are read-only, including their position values. Market methods reject future-date requests; `_bundle` is an implementation detail, not a strategy API. The runner applies company events before phases and values all held positions afterward.

`TargetValue` is a desired holding value; `BuyValue` is an incremental cash budget inclusive of fees. `BuyValue.max_positions` optionally caps new positions while allowing later candidates to replace rejected orders. `Keep` makes no change. Unfilled intents expire; the strategy must reissue them if appropriate.

## Deliberate limits

Long-only stock/fund positions, daily close fills, no queues, partial liquidity, market impact, live gateways or optimizer. Stock settlement and fund settlement are instrument rules, independent of execution timing. Price-limit fallbacks and conservative fund rules are approximations, not market-rule certification. Fees are a configurable static original-strategy model.

Run `pytest` offline. Real probes require `QUANTLAB_LIVE=1`; AKShare needs no token, other providers require their own credentials. Never save credentials in fixtures. Contract error tests must distinguish a malformed request from legitimate missing market data. AKShare mapping details and coverage gaps are in [AKSHARE_CONTRACT.md](AKSHARE_CONTRACT.md).
