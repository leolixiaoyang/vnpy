# Validation record

Implementation based on `my_second_strategy` commit `297551cb537baaf8455d0259c1496c3cad899d60`, branch `feat/lightweight-research-core`.

## Verified locally

- Version 0.3.0, Python 3.12.14, pandas 2.2.3: 98 tests passed; one opt-in broad live test skipped.
- Clean acceptance environment, pandas 3.1.0: same 98 tests passed, one skipped.
- Wheel built by hatchling; installed into a fresh virtual environment with only declared core dependencies.
- From `/tmp`, outside the repository, `quantlab doctor`, synthetic snapshot creation and full offline backtest succeed.
- Fresh core environment has no vnpy, jqdata, jqfactor, AKShare, tinyshare or official tushare SDK installed. Installed imports resolve to site-packages, not repository paths. Default doctor correctly reports AKShare selected, no credential required, SDK absent; synthetic snapshot and offline backtest still succeed.
- Deterministic synthetic scenario triggers monthly selection, a stop-loss and refill; repeated runs produce equal transactions and daily equity. This is infrastructure acceptance, not historical performance evidence.
- Raw Tushare-shaped preparation integration validates endpoint routing, units, historical-constituent union and monthly valuation dates.
- AST dependency checks, snapshot hashes, report provenance and git whitespace checks are included or run separately.
- AKShare fixtures exercise stock/ETF/LOF routes, within-source price fallback, raw and normalized units, ambiguous Sina volume, missing dates, adjustment ratios, quarterly field mappings, announcement gates for derived growth, negative net-cash TTM, stock/fund dividends, scoped listing metadata, provider override and cached quality replay (including strict rejection).
- Preparation integration verifies symbol-scoped metadata/valuations, historical constituent filtering and skipping unsupported historical limit queries. Existing Tushare contracts and accounting/strategy tests remain passing.
- Real CNInfo sampling exposed separate cash and bonus notices sharing an ex-date (600519, 2006-05-19). A regression fixture checks that distinct cash/bonus legs combine with their actual payment/listing dates and latest notice date; ambiguous cash conflicts still fail. Out-of-interval ex-dates do not block an initially empty account.

## AKShare online sampling, 2026-10-23

AKShare 1.19.1 installed separately from the core acceptance environment. Explicit network calls through the adapter returned:

| Sample | Observed result |
| --- | --- |
| `600519.SH`, daily valuation, 2026-04-30 | One normalized row; market caps, shares, static/TTM PE, PB and PS_TTM populated |
| `600519.SH`, report indicators, report periods 2025-01-01 through 2026-04-30 | Five rows; quarter EPS/ROE/ROA/margins and revenue/operating-profit growth populated |
| `600519.SH`, balance sheet and cashflow, announcements 2025-01-01 through 2026-04-30 | Six rows each; liabilities, equity, retained profit, operating and net cash distinct |
| `600519.SH`, stock daily, 2026-04-01 through 2026-04-30 | 21 rows with prices, volume and amount |
| `518880.SH`, `513030.SH`, `513100.SH`, `164824.SZ`, `159866.SZ`, same April window | 21 daily rows each, including the configured LOF |
| `000300.SH`, same April window | 21 rows; Sina index lacks amount, retained as missing |
| Listing metadata | Both exchange lists succeeded in a retry after one transient bulk failure; CNInfo per-stock profile supplied the real 600519 listing date. Preparation uses scoped profiles |
| `600519.SH`, distributions | 31 implemented historical events returned; source per-ten-share units converted |

Calendar and CNI samples were also nonempty. CNI history returned only a current dated snapshot in the sampled response, so no full historical membership claim is made. Some Eastmoney quote endpoints failed in this environment; Sina quote fallback succeeded. The fund volume documentation conflicts with the observed KLC amount/volume/price relationship; the adapter records the unit inference and blocks trades if it cannot determine the unit.

A real-data preparation and offline backtest also completed for 2026-04-01 through 2026-04-30 with an explicitly reduced pool (600519/000001 and funds 518880/164824). The snapshot contained 124 stock bars, 124 fund bars, 124 index bars, two monthly valuation rows and the stocks' reports. Historical constituents were empty, so the configured fallback pools were used; fund adjustments and historical ST/limits remained unavailable and labelled. The run exported 21 trading days and no orders (the small pool produced no selected targets). This verifies the preparation/snapshot/report pipeline, not trading performance. First preparation exceeded a five-minute external test limit; resuming reused completed raw queries and finished. No eight-year full-universe run is claimed.

These are limited data-access/contract samples. They do not establish complete 2018–2026 coverage, accurate financial restatement history, corporate-event completeness or exact strategy performance. Empty and unsupported datasets remain explicit in quality logs. See [AKShare contract and sources](AKSHARE_CONTRACT.md).

## Tushare / tinyshare not online-verified

No tinyshare installation or Tushare/tinyshare credentials are configured in this environment. Their real probes were not executed and the broad opt-in live test is intentionally skipped. No token removed from source was reused or sent to another service. The implementation and documentation distinguish standard-schema validation from live account permissions.

Run the explicit provider probe and optional test in an environment with the selected SDK and its own credentials:

```bash
quantlab doctor --provider tinyshare --config configs/all_weather_rotation.toml --probe
QUANTLAB_LIVE=1 QUANTLAB_PROVIDER=tinyshare pytest -m live
```

Empty endpoint responses are unverified, not success. Probe samples are local snapshots and may require a trading date and sufficient report history. Five configured fund codes, including LOF 164824.SZ, are checked individually.

## Known model/data limits

Same-day close signals and fills are optimistic. No intraday queues, volume caps or live connectivity are implemented. Fund settlement defaults conservatively to T+1 until verified. Current financial providers do not establish complete historical revision lineage; ROIC and some quarterly formula mappings are explicit proxies. Strict mode will reject these. Research mode includes them in the experiment's quality log.

Corporate events depend on provider coverage. Same-day record/ex dates use labelled day-start entitlement approximation; dividend tax and fractional bonus shares are not exact tax-lot modeling. Fixed original commissions/tax are not a historical tax-rate schedule. These limits remain visible in documentation and run metadata.
