# Tushare data contract and provenance

Reviewed against official documentation on 2026-10-23. This records documented contracts, not successful authentication with the user's account. Use `doctor --probe` to produce provider-specific verification and response samples.

## Transport

- Python SDK `pro.query(api_name, fields=..., **params)` returns pandas DataFrame.
- HTTP contract: api_name/token/params/fields; success data.fields + data.items. The core uses the selected SDK rather than implementing an undocumented gateway.
- Dates at the transport boundary are YYYYMMDD. Date windows and row caps are endpoint-specific. SDK errors are sanitized before logging because provider messages can contain credentials.
- tinyshare and official tushare are separate optional transports. Their installations, tokens and permissions are not interchangeable or automatically selected.

Sources: [official request/response](https://tushare.pro/document/2?doc_id=40), [official client implementation](https://github.com/waditu/tushare/blob/master/tushare/pro/client.py).

## Normalization

| Endpoint | Special handling |
| --- | --- |
| daily / index_daily / fund_daily | vol hands ×100; amount thousand yuan ×1000; no adj argument |
| daily_basic | total_mv/circ_mv ten-thousand yuan ×10000; share fields ten-thousand shares ×10000; no EPS field |
| balancesheet | total_share already shares; retain total_liab and total_hldr_eqy_inc_min_int separately |
| fina_indicator | start/end window is report period under current docs; still filter ann_date locally |
| income / balancesheet / cashflow | start/end window is announcement date; f_ann_date preferred for local visibility |
| index_weight | monthly dated snapshots, never select a snapshot later than the decision date |
| stk_limit | up_limit/down_limit preferred over estimated fixed percentages |
| fund_div | div_cash is yuan per share, not per ten units |

Required columns, allowed fields and caps are in `quantlab.data.schemas`. A response at the cap is recursively split by date; an unsplittable cap is an error, never complete coverage. Preparation switches market-wide capped valuations/limits to scoped symbol requests. Financial statement requests are single-symbol consolidated cumulative reports; local filters use report_type=1.

Raw caches are namespaced by provider/SDK, normalization version, endpoint, fields and non-window parameters. A covering date window can satisfy a narrower request. No-data responses can be cached; failed requests cannot.

Sources: [daily](https://tushare.pro/document/2?doc_id=27), [daily_basic](https://tushare.pro/document/2?doc_id=32), [fina_indicator](https://tushare.pro/document/2?doc_id=79), [income](https://tushare.pro/document/2?doc_id=33), [balancesheet](https://tushare.pro/document/2?doc_id=36), [cashflow](https://tushare.pro/document/2?doc_id=44), [index_weight](https://tushare.pro/document/2?doc_id=96), [fund_daily](https://tushare.pro/document/2?doc_id=127), [fund_adj](https://tushare.pro/document/2?doc_id=199), [fund_div](https://tushare.pro/document/2?doc_id=120), [dividend](https://tushare.pro/document/2?doc_id=103), [limits](https://tushare.pro/document/2?doc_id=183).

## Historical visibility and approximation

Reports are visible starting the session after their effective announcement date, never simply at end_date. Choose only a report version with publication date before the decision; an unresolvable duplicate is an error. A current vendor response does not prove complete historical revision lineage, so financial reads carry revision_history_unverified.

Original JoinQuant percentage thresholds stay in percentage points. Direct quarterly q_* metrics are preferred; cumulative proxies are labelled. Tushare roa is return on assets, not JoinQuant's net-profit ROA: use q_npta/npta as an explicitly documented cross-vendor proxy. Tushare roic/100 is labelled roic_ttm_proxy rather than falsely claimed exact. Missing condition fields skip that condition only in research mode and identify affected securities. Missing ordering fields exclude candidates rather than manufacture ranks.

PCF is total market capitalization / TTM n_incr_cash_cash_equ. The TTM formula for a non-December cumulative report is latest YTD + preceding December annual - prior-year same-period YTD, using only reports visible at the decision date. A zero denominator is missing; negative PCF retains the original less-than comparisons. PS uses ps_ttm, static PE uses pe, and TTM PE uses pe_ttm.

Strict mode rejects any approximation; some providers cannot supply enough information for exact mode. Reports must not label those runs exact or online-verified.
