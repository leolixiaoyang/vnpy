# Development context

This branch is an independent quantlab package, not the vnpy source tree. Read README.md and docs/DEVELOPMENT.md.

- Install `.[test]`; run `python -m pytest`.
- Keep SDK imports lazy, optional, and isolated to data/transports.py.
- Never hard-code credentials or print provider exception bodies.
- Preserve Tushare endpoint-specific units and point-in-time rules.
- Do not change JoinQuant strategy thresholds as an incidental refactor.
- Strict mode rejects approximations; research mode records them.
- Same-day close execution is an explicit approximation, not a live execution guarantee.
