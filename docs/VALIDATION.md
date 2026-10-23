# Validation record

Implementation based on `my_second_strategy` commit `297551cb537baaf8455d0259c1496c3cad899d60`, branch `feat/lightweight-research-core`.

## Verified locally

- Python 3.12.14, pandas 2.2.3: 70 tests passed; one opt-in live test skipped.
- Clean acceptance environment, pandas 3.1.0: same 70 tests passed, one skipped.
- Wheel built by hatchling; installed into a fresh virtual environment with only declared core dependencies.
- From `/tmp`, outside the repository, `quantlab doctor`, synthetic snapshot creation and full offline backtest succeed.
- Fresh environment has no vnpy, jqdata, jqfactor, tinyshare or official tushare SDK installed. Installed imports resolve to site-packages, not repository paths.
- Deterministic synthetic scenario triggers monthly selection, a stop-loss and refill; repeated runs produce equal transactions and daily equity. This is infrastructure acceptance, not historical performance evidence.
- Raw Tushare-shaped preparation integration validates endpoint routing, units, historical-constituent union and monthly valuation dates.
- AST dependency checks, snapshot hashes, report provenance and git whitespace checks are included or run separately.

## Not online-verified

No tinyshare installation or provider credentials are configured in this environment. Real probes were not executed and the opt-in live test is intentionally skipped. No token removed from source was reused or sent to another service. The implementation and documentation distinguish standard-schema validation from live account permissions.

Run the explicit provider probe and optional test in an environment with the selected SDK and its own credentials:

```bash
quantlab doctor --provider tinyshare --config configs/all_weather_rotation.toml --probe
QUANTLAB_LIVE=1 QUANTLAB_PROVIDER=tinyshare pytest -m live
```

Empty endpoint responses are unverified, not success. Probe samples are local snapshots and may require a trading date and sufficient report history. Five configured fund codes, including LOF 164824.SZ, are checked individually.

## Known model/data limits

Same-day close signals and fills are optimistic. No intraday queues, volume caps or live connectivity are implemented. Fund settlement defaults conservatively to T+1 until verified. Current financial providers do not establish complete historical revision lineage; ROIC and some quarterly formula mappings are explicit proxies. Strict mode will reject these. Research mode includes them in the experiment's quality log.

Corporate events depend on provider coverage. Same-day record/ex dates use labelled day-start entitlement approximation; dividend tax and fractional bonus shares are not exact tax-lot modeling. Fixed original commissions/tax are not a historical tax-rate schedule. These limits remain visible in documentation and run metadata.
