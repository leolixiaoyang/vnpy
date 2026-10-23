# JoinQuant all-weather rotation: rule mapping

Reference: `new_strategy_stratch.py`, MarioC's original [JoinQuant article](https://www.joinquant.com/post/48819). The reference remains read-only and is never imported. Research execution approximates the original 09:30 and 14:00 actions at the same daily close.

| Original rule | Independent implementation / acceptance |
| --- | --- |
| prior-session pools, old listings, board/ST filtering | MarketDataView.eligible + constituents; historical snapshots with explicit fallback |
| top/bottom 20 circulating caps, ten-bar return | _strong; adjusted signal prices; invalid group does not force funds |
| >10 strong market, otherwise positive winner, ties | regime; equal strong picks small, equal ordinary picks funds |
| SMALL ROE>.15 ROA>.10, total-cap ascending | quarterly percentage-point proxies, up to stock_num*3 |
| BIG PE 0..30, PS 0..8, PCF<10, EPS>.3, ROE>.1, net margin>.1, gross margin>.3, revenue growth>.25 | all predicates restored; total-cap descending; stock_num |
| ROIC_BIG cap>300×1e8 yuan, PE 0..50, EPS>.12, ROA>.15, liabilities/equity<.5, total revenue growth>.3, revenue growth>.2, retained profit>0, ROIC_TTM>.08 | retained-profit descending; ROIC proxy labelled |
| BM cap100..900×1e8, PB0..10, PCF<4, EPS>.3, ROE>.2, net margin>.1, revenue growth>.2, operating-profit growth>.1 | all predicates restored; total-cap ascending |
| union of three large-cap selectors | original concatenation order, deterministic de-duplication instead of set iteration |
| five fallback funds | original codes retained, including LOF 164824.SZ; live coverage must be probed individually |
| keep yesterday-limit-up outsiders | day-start and prior-limit snapshots; monthly removals exempt them |
| fill missing positions only | no forced equal-weight rebalance; denominator target count minus actual position count |
| open-board exit then cost×.92 stop | one exit intent per symbol; actual fill and settlement decide outcome |
| refill three largest surviving losers | distinct symbols; fixed cash/3 even with only one or two survivors |

The original threshold 0.15 is **0.15%**, not 15%. Source: [official JoinQuant field definitions](https://github.com/JoinQuant/jqdatasdk/blob/master/jqdatasdk/finance_tables.py). [Official valuation docs](https://github.com/JoinQuant/jqdatasdk/blob/master/jqdatasdk/api.py) distinguish ps_ratio TTM and pcf_ratio net-cashflow TTM from operating-cashflow pcf_ratio2.

Intentional corrections: cumulative holding accounting, fee-aware cash limits, distinct equal-PnL refill candidates, deterministic union order, no proceeds from rejected sells, valid stale valuation and no first-day rebalance when starting mid-month. These change old second results; no golden net value from its broken account logic is retained.

Cross-vendor period/formula differences are recorded rather than hidden. A complete port of rule structure does not establish identical data or returns to JoinQuant.
