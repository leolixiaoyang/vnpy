"""Build a self-contained, explicitly degraded snapshot from standard endpoints."""
from datetime import date, timedelta

import pandas as pd

from ..quality import DataError
from .bundle import DataBundle
from .provider import tsdate


def combine(frames):
    return pd.concat([f for f in frames if not f.empty], ignore_index=True).drop_duplicates() if any(not f.empty for f in frames) else pd.DataFrame()


def corporate_table(tables, quality, start=None, end=None):
    actions = []
    for api in ["dividend", "fund_div"]:
        df = tables.get(api, pd.DataFrame())
        if not df.empty and start is not None and "ex_date" in df:
            # Initial holdings are empty; only this interval's ex-dates affect it.
            df = df[df.ex_date.between(start, end)]
        for _, row in df.iterrows():
            if pd.isna(row.get("ex_date")) or pd.isna(row.get("record_date")):
                continue
            if row.get("div_proc") != "实施":
                continue
            if api == "fund_div":
                # Official fund_div.div_cash is yuan PER SHARE, not per ten shares.
                cash = float(row.get("div_cash", 0) or 0)
                ratio = 0.0
                listing = row.ex_date
            else:
                cash = row.get("cash_div_tax")
                if pd.isna(cash):
                    cash = row.get("cash_div", 0)
                ratio, listing = row.get("stk_div", 0), row.get("div_listdate")
            quality.record("dividend_tax_unmodeled", row.ts_code)
            actions.append({"ts_code": row.ts_code, "ann_date": row.get("ann_date"),
                            "record_date": row.record_date, "ex_date": row.ex_date,
                            "pay_date": row.get("pay_date"), "cash_per_share": float(cash) if pd.notna(cash) else 0.0,
                            "share_ratio": float(ratio) if pd.notna(ratio) else 0.0, "list_date": listing})
    result = pd.DataFrame(actions)
    if not result.empty:
        meaningful = ["ts_code", "record_date", "ex_date", "pay_date", "cash_per_share", "share_ratio", "list_date"]
        result = result.sort_values("ann_date").drop_duplicates(meaningful, keep="first")
        if result.duplicated(["ts_code", "ex_date"]).any():
            raise DataError("Conflicting implemented corporate actions on the same ex-date")
    return result


def prepare(provider, config):
    backtest, strategy = config["backtest"], config.get("strategy", {})
    params = strategy.get("parameters", {})
    start, end = backtest["start"], backtest["end"]
    warmup = (date.fromisoformat(start) - timedelta(days=65)).isoformat()
    history = (date.fromisoformat(start) - timedelta(days=5 * 366)).isoformat()
    tables = {}
    tables["trade_cal"] = provider.fetch("trade_cal", {"exchange": "SSE", "start_date": warmup, "end_date": end})
    calendars = tables["trade_cal"]
    if calendars.empty:
        raise DataError("No calendar returned")
    sessions = sorted(calendars[calendars.is_open == 1].cal_date.unique())
    if len([d for d in sessions if d < start]) < 10:
        provider.quality.record("short_warmup", "Provider calendar has fewer than ten prior sessions")
    scoped_metadata = getattr(provider.transport, "metadata_by_symbol", False)
    if not scoped_metadata:
        tables["stock_basic"] = combine([provider.fetch("stock_basic", {"list_status": s}) for s in ["L", "D", "P"]])
    big, small = params.get("big_index", "000300.SH"), params.get("small_index", "399101.SZ")
    benchmark = backtest.get("benchmark", big)
    indices = sorted({big, small, benchmark})
    index_frames, weights, metadata = [], [], []
    for symbol in indices:
        info = provider.fetch("index_basic", {"ts_code": symbol})
        if info.empty:
            raise DataError(f"Index code is not recognized by index_basic: {symbol}")
        metadata.append(info)
        index_frames.append(provider.fetch("index_daily", {"ts_code": symbol, "start_date": warmup, "end_date": end}))
        if symbol in {big, small}:
            weights.append(provider.optional("index_weight", {"index_code": symbol, "start_date": warmup, "end_date": end}))
    tables["index_basic"], tables["index_daily"], tables["index_weight"] = combine(metadata), combine(index_frames), combine(weights)
    funds = params.get("funds", ["518880.SH", "513030.SH", "513100.SH", "164824.SZ", "159866.SZ"])
    fund_info, fund_bars, fund_factors, fund_dividends = [], [], [], []
    for symbol in funds:
        info = provider.fetch("fund_basic", {"ts_code": symbol, "market": "E"})
        if info.empty:
            provider.quality.record("unrecognized_fund", symbol)
            continue
        fund_info.append(info)
        fund_bars.append(provider.optional("fund_daily", {"ts_code": symbol, "start_date": warmup, "end_date": end}))
        fund_factors.append(provider.optional("fund_adj", {"ts_code": symbol, "start_date": warmup, "end_date": end}))
        fund_dividends.append(provider.optional("fund_div", {"ts_code": symbol}))
    tables["fund_basic"], tables["fund_daily"] = combine(fund_info), combine(fund_bars)
    tables["fund_adj"], tables["fund_div"] = combine(fund_factors), combine(fund_dividends)
    stocks = set(tables["index_weight"].con_code) if not tables["index_weight"].empty else set()
    for pool in config.get("fallback_pools", {}).values():
        stocks.update(pool)
    stocks = sorted(s for s in stocks if not s.startswith(("3", "4", "8", "68", "92")) and not s.endswith(".BJ"))
    if not stocks:
        raise DataError("No historical constituents or configured fallback stock pool")
    if scoped_metadata:
        tables["stock_basic"] = combine([provider.optional("stock_basic", {"ts_code": s, "list_status": "L"}) for s in stocks])
        if tables["stock_basic"].empty:
            raise DataError("No stock listing metadata returned for the strategy pool")
        missing = set(stocks) - set(tables["stock_basic"].ts_code)
        if missing:
            provider.quality.record("missing_stock_metadata", ", ".join(sorted(missing)))
    by_endpoint = {k: [] for k in ["daily", "adj_factor", "namechange", "fina_indicator", "income", "balancesheet", "cashflow", "dividend"]}
    for symbol in stocks:
        for endpoint in by_endpoint:
            if endpoint == "dividend":
                request = {"ts_code": symbol}
            else:
                lo = history if endpoint in {"fina_indicator", "income", "balancesheet", "cashflow", "namechange"} else warmup
                request = {"ts_code": symbol, "start_date": lo, "end_date": end}
            by_endpoint[endpoint].append(provider.optional(endpoint, request))
    tables.update({k: combine(v) for k, v in by_endpoint.items()})
    # Valuations are only consumed at the previous session of each rebalance day.
    valuation_dates = [sessions[i - 1] for i, d in enumerate(sessions) if i > 0 and start <= d <= end and d[:7] != sessions[i - 1][:7]]
    valuations = []
    for d in valuation_dates:
        if getattr(provider.transport, "valuation_by_symbol", False):
            valuations.extend(provider.optional("daily_basic", {"trade_date": d, "ts_code": s}) for s in stocks)
            continue
        try:
            valuations.append(provider.optional("daily_basic", {"trade_date": d}))
        except DataError as exc:
            if "truncation" not in str(exc):
                raise
            valuations.extend(provider.optional("daily_basic", {"trade_date": d, "ts_code": s}) for s in stocks)
    tables["daily_basic"] = combine(valuations)
    limit_frames = []
    if not getattr(provider.transport, "historical_limits", True):
        provider.quality.record("provider_unavailable", "stk_limit: historical dataset unavailable; limits will be estimated")
    for d in sessions if getattr(provider.transport, "historical_limits", True) else []:
        # Query by symbol when the market-wide cap is reached instead of caching truncation.
        try:
            frame = provider.optional("stk_limit", {"trade_date": d})
        except DataError as exc:
            if "truncation" not in str(exc):
                raise
            frame = combine([provider.optional("stk_limit", {"trade_date": d, "ts_code": s}) for s in stocks + list(funds)])
        limit_frames.append(frame)
    tables["stk_limit"] = combine(limit_frames)
    tables["corporate_actions"] = corporate_table(tables, provider.quality, start, end)
    if tables["corporate_actions"].empty:
        provider.quality.record("corporate_action_coverage_unverified", "No implemented events in the backtest interval; coverage not proven")
    return DataBundle(tables, {"provider": getattr(provider.transport, "provider", "injected"),
                             "sdk_version": getattr(provider.transport, "version", "injected"),
                             "start": start, "end": end, "warmup": warmup,
                             "mapping_version": getattr(provider.transport, "mapping_version", "joinquant-tushare-v1"),
                             "quality": provider.quality.export()})
