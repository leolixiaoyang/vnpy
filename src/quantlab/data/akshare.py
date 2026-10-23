"""AKShare -> shared table contract (no Tushare service or credentials involved).

Units here match the raw contract; normalization converts them exactly once.
Upstream data is memoized per SDK function/arguments during preparation.
"""
import importlib
import re
from bisect import bisect_left

import pandas as pd

from ..quality import DataError, QualityLog
from .schemas import SCHEMAS, validate_request
from .transports import ProviderError


def dates(values):
    text = values.astype("string").str.replace(r"\.0$", "", regex=True)
    return pd.to_datetime(text, errors="coerce", format="mixed").dt.strftime("%Y%m%d").astype("string")


def require(frame, columns, source):
    missing = set(columns) - set(frame)
    if not frame.empty and missing:
        raise DataError(f"{source}: missing columns {sorted(missing)}")


def numbers(frame, column):
    if column not in frame:
        return pd.Series(float("nan"), index=frame.index)
    values = frame[column].replace({"--": None, "-": None, "": None})
    result = pd.to_numeric(values, errors="coerce")
    if (values.notna() & result.isna()).any():
        raise DataError(f"AKShare: invalid numeric values in {column}")
    return result


def symbol_parts(symbol):
    if not re.fullmatch(r"\d{6}\.(SH|SZ)", symbol or ""):
        raise DataError("AKShare requires a six-digit .SH or .SZ symbol")
    code, exchange = symbol.split(".")
    return code, exchange


def stock_symbol(code):
    code = str(code).removesuffix(".0").zfill(6)
    if not re.fullmatch(r"\d{6}", code):
        raise DataError("AKShare returned an invalid stock code")
    if code.startswith(("4", "8", "92")):
        return code + ".BJ"
    return code + (".SH" if code.startswith("6") else ".SZ")


class AKShareTransport:
    provider = "akshare"
    mapping_version = "akshare-v1"
    valuation_by_symbol = True
    metadata_by_symbol = True
    historical_limits = False
    unsupported = frozenset({"stk_limit", "namechange"})

    def __init__(self, client=None, quality=None, start="2018-01-01", end="2026-04-30",
                 lof_symbols=("164824.SZ",)):
        if client is None:
            try:
                client = importlib.import_module("akshare")
            except ImportError:
                raise ProviderError("sdk_not_installed", "akshare") from None
        self.client = client
        self.version = str(getattr(client, "__version__", "injected"))
        self.quality = quality if quality is not None else QualityLog()
        self.start, self.end = start, end
        self.lof_symbols = set(lof_symbols)
        self._memo, self._sources, self._notes = {}, {}, []

    def _note(self, code, detail):
        event = {"code": code, "detail": detail}
        if event not in self._notes:
            self._notes.append(event)
        self.quality.record(code, detail)

    def _call(self, function, **kwargs):
        key = (function, tuple(sorted(kwargs.items())))
        if key not in self._memo:
            try:
                frame = getattr(self.client, function)(**kwargs)
            except Exception:
                # Exception messages may contain URLs or credentials from SDK internals.
                raise ProviderError("upstream_unavailable", function) from None
            if not isinstance(frame, pd.DataFrame):
                raise DataError(f"{function}: SDK must return pandas.DataFrame")
            self._memo[key] = frame.copy()
        return self._memo[key].copy()

    def query(self, api_name, params, fields):
        validate_request(api_name, params, fields)
        self._notes = []
        if api_name in self.unsupported:
            raise ProviderError("historical_dataset_unavailable", api_name)
        required = ({"start_date", "end_date"} if api_name == "trade_cal" else
                    {"index_code"} if api_name == "index_weight" else
                    set() if api_name in {"stock_basic", "daily_basic"} else {"ts_code"})
        if required - params.keys():
            raise DataError(f"{api_name}: AKShare requires {sorted(required)}")
        if ("start_date" in params) != ("end_date" in params):
            raise DataError(f"{api_name}: AKShare requires both start_date and end_date")
        handlers = {"daily": lambda: self._bars("stock", params["ts_code"]),
                    "index_daily": lambda: self._bars("index", params["ts_code"]),
                    "fund_daily": lambda: self._bars("fund", params["ts_code"]),
                    "adj_factor": lambda: self._factors("stock", params["ts_code"]),
                    "fund_adj": lambda: self._factors("fund", params["ts_code"]),
                    "fina_indicator": lambda: self._indicators(params["ts_code"]),
                    "income": lambda: self._statement("income", params["ts_code"]),
                    "balancesheet": lambda: self._statement("balancesheet", params["ts_code"]),
                    "cashflow": lambda: self._statement("cashflow", params["ts_code"]),
                    "dividend": lambda: self._dividend(params["ts_code"]),
                    "fund_div": lambda: self._fund_div(params["ts_code"]),
                    "daily_basic": lambda: self._valuations(params.get("ts_code")),
                    "stock_basic": lambda: self._stock_basic(params),
                    "fund_basic": lambda: self._fund_basic(params),
                    "index_basic": lambda: self._index_basic(params),
                    "index_weight": lambda: self._weights(params["index_code"]),
                    "trade_cal": lambda: self._calendar(params)}
        frame = handlers[api_name]()
        if not frame.empty:
            for column in SCHEMAS[api_name].required:
                if column not in frame or frame[column].isna().any():
                    raise DataError(f"{api_name}: AKShare missing required values in {column}")
            axis = SCHEMAS[api_name].date_axis
            if axis and "start_date" in params:
                frame = frame[frame[axis].between(params["start_date"], params["end_date"])]
            for key, value in params.items():
                if key in {"start_date", "end_date"}:
                    continue
                if key == "period":
                    frame = frame[frame.end_date == value]
                elif key in frame:
                    frame = frame[frame[key].astype(str) == str(value)]
                else:
                    raise DataError(f"{api_name}: AKShare filter is unsupported: {key}")
        result = frame.reindex(columns=fields).reset_index(drop=True)
        result.attrs["quality"] = list(self._notes)
        return result

    def _calendar(self, params):
        raw = self._call("tool_trade_date_hist_sina")
        require(raw, ["trade_date"], "tool_trade_date_hist_sina")
        if raw.empty:
            raise ProviderError("empty_calendar", "trade_cal")
        converted = dates(raw.trade_date)
        if converted.isna().any():
            raise DataError("AKShare calendar contains invalid dates")
        opens = sorted(converted.unique())
        if not opens:
            raise DataError("AKShare calendar contains no valid dates")
        lo, hi = params["start_date"], params["end_date"]
        if lo < opens[0] or hi > opens[-1]:
            raise DataError(f"AKShare calendar does not cover requested {lo}..{hi}")
        days = pd.date_range(lo, hi).strftime("%Y%m%d")
        frame = pd.DataFrame({"cal_date": days, "exchange": params.get("exchange", "SSE")})
        frame["is_open"] = frame.cal_date.isin(opens).astype(int)
        # Calendar previous session, including the open session preceding the request.
        frame["pretrade_date"] = [opens[bisect_left(opens, d) - 1] if bisect_left(opens, d) > 0 else None for d in days]
        return frame

    def _stock_basic(self, params):
        self._note("akshare_listing_survivorship", "Current SH/SZ listings; delisted/suspended listing history is incomplete")
        if params.get("list_status", "L") != "L":
            return pd.DataFrame()
        if params.get("ts_code"):
            symbol = params["ts_code"]
            code, exchange = symbol_parts(symbol)
            raw = self._call("stock_profile_cninfo", symbol=code)
            require(raw, ["A股代码", "A股简称", "上市日期"], "stock_profile_cninfo")
            if raw.empty:
                return raw
            frame = pd.DataFrame({"ts_code": raw["A股代码"].map(stock_symbol), "name": raw["A股简称"],
                                  "list_date": dates(raw["上市日期"]), "exchange": "SSE" if exchange == "SH" else "SZSE", "list_status": "L"})
            self._note("akshare_scoped_listing_metadata", "CNInfo company profiles for the requested pool; current names, historical listing status not established")
            return frame
        frames = []
        for fn, arg, code, name, listed, exchange in [
            ("stock_info_sh_name_code", "主板A股", "证券代码", "证券简称", "上市日期", "SSE"),
            ("stock_info_sz_name_code", "A股列表", "A股代码", "A股简称", "A股上市日期", "SZSE")]:
            raw = self._call(fn, symbol=arg)
            require(raw, [code, name, listed], fn)
            if raw.empty:
                continue
            frame = pd.DataFrame({"ts_code": raw[code].map(stock_symbol), "name": raw[name],
                                  "list_date": dates(raw[listed]), "exchange": exchange, "list_status": "L"})
            frames.append(frame)
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

    def _fund_basic(self, params):
        raw = self._call("fund_name_em")
        require(raw, ["基金代码", "基金简称", "基金类型"], "fund_name_em")
        if raw.empty:
            return raw
        self._note("akshare_fund_metadata_current", "Fund names/types are current; listing/delisting dates unavailable")
        code, _ = symbol_parts(params["ts_code"])
        raw = raw[raw["基金代码"].astype(str).str.zfill(6) == code]
        return pd.DataFrame({"ts_code": params["ts_code"], "name": raw["基金简称"],
                             "fund_type": raw["基金类型"], "market": "E"})

    def _index_basic(self, params):
        # Only these identities are needed by the shipped strategy; no guessed catalog.
        names = {"000300.SH": ("沪深300", "CSI"), "399101.SZ": ("中小综指", "SZSE")}
        symbol = params["ts_code"]
        if symbol not in names:
            raise ProviderError("index_metadata_unsupported", "index_basic")
        name, publisher = names[symbol]
        self._note("akshare_index_metadata_registry", "Index identities from the documented strategy registry")
        return pd.DataFrame([{"ts_code": symbol, "name": name, "publisher": publisher}])

    def _bars(self, kind, symbol, adjust=""):
        code, exchange = symbol_parts(symbol)
        prefix = exchange.lower() + code
        primary = ("stock_zh_a_hist" if kind == "stock" else "stock_zh_index_daily_em" if kind == "index"
                   else "fund_lof_hist_em" if symbol in self.lof_symbols else "fund_etf_hist_em")
        fallback = "stock_zh_a_daily" if kind == "stock" else "stock_zh_index_daily" if kind == "index" else "fund_etf_hist_sina"
        source = self._sources.get((kind, symbol), primary)
        if source == primary:
            kwargs = {"symbol": prefix if kind == "index" else code, "start_date": "19900101", "end_date": "20991231"}
            if kind != "index":
                kwargs.update(period="daily", adjust=adjust)
            try:
                raw = self._call(primary, **kwargs)
                if raw.empty:
                    raise ProviderError("empty_prices", primary)
            except ProviderError:
                source = fallback
        if source == fallback:
            self._note("akshare_price_source_fallback", f"{symbol}: {primary} -> {fallback}")
            kwargs = {"symbol": prefix}
            if kind == "stock":
                kwargs.update(start_date="19900101", end_date="20991231", adjust=adjust)
            elif adjust:
                raise ProviderError("adjusted_prices_unavailable", fallback)
            raw = self._call(fallback, **kwargs)
        if not adjust:
            self._sources[(kind, symbol)] = source
        if raw.empty:
            return pd.DataFrame()
        chinese = source == primary and kind != "index"
        rename = {"日期": "trade_date", "开盘": "open", "最高": "high", "最低": "low", "收盘": "close", "成交量": "vol", "成交额": "amount"}
        frame = raw.rename(columns=rename if chinese else {"date": "trade_date", "volume": "vol"}).copy()
        require(frame, ["trade_date", "open", "high", "low", "close", "vol"], source)
        frame["trade_date"] = dates(frame.trade_date)
        frame = frame.sort_values("trade_date")
        for col in ["open", "high", "low", "close", "vol", "amount"]:
            frame[col] = numbers(frame, col)
        # Eastmoney stock/fund volume is lots; Sina stock volume is shares.
        if kind == "index":
            frame["vol"] = float("nan")
            self._note("akshare_index_volume_unknown", f"{symbol}: upstream volume unit unspecified; index signals use close only")
        elif kind == "fund" and source == fallback:
            # The fund docs label lots, but live KLC data with amount is shares.
            # Check turnover against prices rather than silently applying a 100x error.
            ratios = (frame.amount / frame.vol.where(frame.vol > 0) / ((frame.high + frame.low) / 2)).dropna()
            ratio = ratios.median() if not ratios.empty else float("nan")
            if pd.notna(ratio) and .5 <= ratio <= 2:
                frame["vol"] /= 100
                unit = "shares"
            elif pd.notna(ratio) and 50 <= ratio <= 200:
                unit = "lots"
            else:
                frame["vol"] = float("nan")
                unit = "unknown (trades blocked)"
            self._note("akshare_sina_fund_volume_inferred", f"{symbol}: {unit}, checked against amount/volume/price; documentation and live data differ")
        elif not chinese:
            frame["vol"] /= 100
        frame["amount"] /= 1000  # yuan -> raw contract's thousand yuan
        if chinese and "涨跌额" in frame:
            frame["pre_close"] = frame.close - numbers(frame, "涨跌额")
        else:
            frame["pre_close"] = frame.close.shift(1)
            self._note("akshare_preclose_proxy", f"{symbol}: previous observed close; ex-date reference may differ")
        frame["ts_code"] = symbol
        self._note("akshare_price_history_coverage", f"{symbol}: {source} history {frame.trade_date.min()}..{frame.trade_date.max()}; no completeness guarantee")
        return frame.reindex(columns=SCHEMAS["daily"].fields)

    def _factors(self, kind, symbol):
        raw = self._bars(kind, symbol)
        adjusted = self._bars(kind, symbol, "hfq")
        if raw.empty or adjusted.empty:
            return pd.DataFrame()
        frame = raw[["ts_code", "trade_date", "close"]].merge(adjusted[["trade_date", "close"]], on="trade_date", suffixes=("", "_hfq"), validate="one_to_one")
        frame["adj_factor"] = frame.close_hfq / frame.close.where(frame.close > 0)
        frame = frame[frame.adj_factor.notna() & (frame.adj_factor > 0)]
        self._note("akshare_adjustment_ratio", f"{symbol}: hfq/raw close ratio; vendor adjustment formula")
        return frame[["ts_code", "trade_date", "adj_factor"]]

    def _valuations(self, symbol):
        if not symbol:
            raise DataError("AKShare daily_basic requires ts_code; no all-market historical valuation endpoint")
        code, _ = symbol_parts(symbol)
        raw = self._call("stock_value_em", symbol=code)
        require(raw, ["数据日期", "总市值", "流通市值"], "stock_value_em")
        if raw.empty:
            return raw
        mapping = {"close": "当日收盘价", "pe": "PE(静)", "pe_ttm": "PE(TTM)", "pb": "市净率", "ps_ttm": "市销率",
                   "total_mv": "总市值", "circ_mv": "流通市值", "total_share": "总股本", "float_share": "流通股本"}
        frame = pd.DataFrame({target: numbers(raw, source) for target, source in mapping.items()})
        for col in ["total_mv", "circ_mv", "total_share", "float_share"]:
            frame[col] /= 10000  # AKShare yuan/shares -> raw contract ten-thousands
        frame["trade_date"], frame["ts_code"] = dates(raw["数据日期"]), symbol
        self._note("akshare_valuation_coverage", f"{symbol}: stock_value_em {frame.trade_date.min()}..{frame.trade_date.max()}; upstream capped history, missing dates stay missing")
        # 市现率 is PCF_OCF_TTM: deliberately NOT used as the strategy's PCF_NET_TTM.
        return frame

    def _statement(self, api, symbol):
        code, exchange = symbol_parts(symbol)
        fn = {"income": "stock_profit_sheet_by_report_em", "balancesheet": "stock_balance_sheet_by_report_em", "cashflow": "stock_cash_flow_sheet_by_report_em"}[api]
        raw = self._call(fn, symbol=exchange + code)
        require(raw, ["REPORT_DATE", "NOTICE_DATE"], fn)
        if raw.empty:
            return raw
        mappings = {
            "income": {"basic_eps": "BASIC_EPS", "revenue": "OPERATE_INCOME", "total_revenue": "TOTAL_OPERATE_INCOME", "operate_profit": "OPERATE_PROFIT", "n_income": "NETPROFIT", "n_income_attr_p": "PARENT_NETPROFIT"},
            "balancesheet": {"total_share": "SHARE_CAPITAL", "total_assets": "TOTAL_ASSETS", "total_liab": "TOTAL_LIABILITIES", "total_hldr_eqy_inc_min_int": "TOTAL_EQUITY", "undistr_porfit": "UNASSIGN_RPOFIT"},
            "cashflow": {"n_cashflow_act": "NETCASH_OPERATE", "n_incr_cash_cash_equ": "CCE_ADD"}}
        frame = pd.DataFrame({target: numbers(raw, source) for target, source in mappings[api].items()})
        # Some report types expose beginning/end balances instead of CCE_ADD.
        if api == "cashflow" and "CCE_ADD" not in raw:
            last, first = ("END_CCE", "BEGIN_CCE") if {"END_CCE", "BEGIN_CCE"} <= set(raw) else ("END_CASH_EQUIVALENTS", "BEGIN_CASH_EQUIVALENTS")
            require(raw, [last, first], fn)
            frame["n_incr_cash_cash_equ"] = numbers(raw, last) - numbers(raw, first)
            self._note("akshare_cash_net_derived", f"{symbol}: ending minus beginning cash equivalents, cumulative yuan")
        frame["ts_code"], frame["end_date"] = symbol, dates(raw.REPORT_DATE)
        frame["ann_date"] = dates(raw.NOTICE_DATE)
        frame["f_ann_date"], frame["report_type"] = frame.ann_date, "1"
        self._note("akshare_financial_revisions_unverified", f"{api} {symbol}: current report versions; complete historical restatements unavailable")
        self._note("akshare_financial_history_coverage", f"{api} {symbol}: report periods {frame.end_date.min()}..{frame.end_date.max()}, {len(frame)} rows")
        if frame.ann_date.isna().any():
            self._note("akshare_missing_announcement", f"{api} {symbol}: rows without publication date excluded")
            frame = frame[frame.ann_date.notna()]
        return frame

    def _indicators(self, symbol):
        symbol_parts(symbol)
        raw = self._call("stock_financial_analysis_indicator_em", symbol=symbol, indicator="按报告期")
        require(raw, ["REPORT_DATE", "NOTICE_DATE"], "stock_financial_analysis_indicator_em")
        if raw.empty:
            return raw
        mapping = {"eps": "EPSJB", "roe": "ROEJQ", "npta": "ZZCJLL", "roic": "ROIC", "netprofit_margin": "XSJLL", "grossprofit_margin": "XSMLL", "tr_yoy": "TOTALOPERATEREVETZ"}
        frame = pd.DataFrame({target: numbers(raw, source) for target, source in mapping.items()})
        frame["ts_code"], frame["end_date"], frame["ann_date"] = symbol, dates(raw.REPORT_DATE), dates(raw.NOTICE_DATE)
        if frame.end_date.isna().any():
            raise DataError("fina_indicator: AKShare missing required values in end_date")
        self._note("akshare_financial_history_coverage", f"fina_indicator {symbol}: report periods {frame.end_date.min()}..{frame.end_date.max()}, {len(frame)} rows; upstream limit 200")
        try:
            quarter = self._call("stock_financial_analysis_indicator_em", symbol=symbol, indicator="按单季度")
            require(quarter, ["REPORT_DATE"], "stock_financial_analysis_indicator_em:quarter")
            if not quarter.empty:
                qm = {"q_eps": "EPSJB", "q_roe": "ROE_DILUTED", "q_npta": "JROA", "q_netprofit_margin": "NET_PROFIT_RATIO", "q_gsprofit_margin": "GROSS_PROFIT_RATIO", "q_gr_yoy": "TOTALOPERATEREVETZ"}
                q = pd.DataFrame({target: numbers(quarter, source) for target, source in qm.items()})
                q["end_date"] = dates(quarter.REPORT_DATE)
                frame = frame.merge(q, on="end_date", how="left", validate="one_to_one")
                self._note("akshare_quarter_formula", f"{symbol}: quarterly diluted ROE/JROA; announcement inherited from corresponding cumulative report")
        except ProviderError:
            self._note("akshare_quarter_unavailable", symbol)
        try:
            income = self._statement("income", symbol)
            frame = self._income_growth(frame, income)
        except ProviderError:
            self._note("akshare_income_growth_unavailable", symbol)
        if frame.ann_date.isna().any():
            self._note("akshare_missing_announcement", f"fina_indicator {symbol}: rows without publication date excluded")
            frame = frame[frame.ann_date.notna()]
        self._note("akshare_financial_revisions_unverified", f"fina_indicator {symbol}: historical versions not established")
        return frame

    def _income_growth(self, frame, income):
        if income.empty:
            return frame
        if income.duplicated("end_date").any():
            raise DataError("AKShare: ambiguous income report versions")
        rows = income.set_index("end_date")

        def value(period, field, quarterly):
            if period not in rows.index:
                return float("nan"), []
            r = rows.loc[period]
            result, announcements = r[field], [r.ann_date]
            if quarterly and not period.endswith("0331"):
                previous = (pd.Timestamp(period) - pd.offsets.QuarterEnd()).strftime("%Y%m%d")
                if previous not in rows.index:
                    return float("nan"), []
                result -= rows.loc[previous, field]
                announcements.append(rows.loc[previous, "ann_date"])
            return result, announcements

        for i, r in frame.iterrows():
            for output, field, quarterly in [("q_sales_yoy", "revenue", True), ("q_op_yoy", "operate_profit", True), ("or_yoy", "revenue", False), ("op_yoy", "operate_profit", False)]:
                current, ann = value(r.end_date, field, quarterly)
                previous, old_ann = value(str(int(r.end_date[:4]) - 1) + r.end_date[4:], field, quarterly)
                frame.loc[i, output] = (current - previous) / abs(previous) * 100 if pd.notna(previous) and previous != 0 else float("nan")
                if pd.notna(frame.loc[i, output]) and pd.notna(frame.loc[i, "ann_date"]):
                    frame.loc[i, "ann_date"] = max([frame.loc[i, "ann_date"], *ann, *old_ann])
        self._note("akshare_growth_derived", "Quarterly income = YTD minus preceding YTD; YoY=(current-prior)/abs(prior)*100; latest input announcement gates availability")
        return frame

    def _weights(self, symbol):
        code, _ = symbol_parts(symbol)
        if symbol == "000300.SH":
            raw = self._call("index_stock_cons_weight_csindex", symbol=code)
            mapping = {"日期": "trade_date", "成分券代码": "con_code", "权重": "weight"}
        else:
            raw = self._call("index_detail_hist_cni", symbol=code)
            mapping = {"日期": "trade_date", "样本代码": "con_code", "权重": "weight"}
        require(raw, list(mapping), "AKShare constituents")
        if raw.empty:
            return raw
        frame = raw.rename(columns=mapping)[list(mapping.values())].copy()
        frame["trade_date"], frame["con_code"] = dates(frame.trade_date), frame.con_code.map(stock_symbol)
        frame["index_code"] = symbol
        self._note("akshare_constituent_history_incomplete", f"{symbol}: only actual dated snapshots; never backfill latest membership into earlier dates")
        return frame

    def _dividend(self, symbol):
        code, _ = symbol_parts(symbol)
        raw = self._call("stock_dividend_cninfo", symbol=code)
        require(raw, ["实施方案公告日期", "股权登记日", "除权日", "派息比例", "送股比例", "转增比例"], "stock_dividend_cninfo")
        if raw.empty:
            return raw
        frame = pd.DataFrame({"ts_code": symbol, "ann_date": dates(raw["实施方案公告日期"]), "record_date": dates(raw["股权登记日"]), "ex_date": dates(raw["除权日"]), "div_proc": "实施"})
        for source, target in [("报告时间", "end_date"), ("派息日", "pay_date"), ("股份到账日", "div_listdate")]:
            if source in raw:
                frame[target] = dates(raw[source])
        frame["cash_div_tax"] = numbers(raw, "派息比例") / 10
        frame["stk_div"] = numbers(raw, "送股比例").add(numbers(raw, "转增比例"), fill_value=0) / 10
        self._note("akshare_corporate_coverage_unverified", f"{symbol}: implemented CNInfo distributions; complete event lineage not established")
        return self._merge_distributions(frame, symbol)

    def _merge_distributions(self, frame, symbol):
        result = []
        for _, group in frame.groupby("ex_date", dropna=False, sort=False):
            if len(group) == 1 or group.ex_date.isna().any():
                result.append(group)
                continue
            # CNInfo can report the cash distribution and bonus issue separately.
            # Combine only one unambiguous cash leg and one unambiguous share leg.
            cash = group[group.cash_div_tax.fillna(0) > 0]
            shares = group[group.stk_div.fillna(0) > 0]
            if (len(group) == 2 and len(cash) == len(shares) == 1
                    and cash.index[0] != shares.index[0]
                    and group.record_date.notna().all() and group.record_date.nunique() == 1
                    and group.ann_date.notna().all()
                    and (group.cash_div_tax.fillna(0) >= 0).all()
                    and (group.stk_div.fillna(0) >= 0).all()):
                row = cash.iloc[[0]].copy()
                row["stk_div"] = shares.stk_div.iloc[0]
                row["ann_date"] = group.ann_date.max()
                if "div_listdate" in group:
                    row["div_listdate"] = shares.div_listdate.iloc[0]
                result.append(row)
                self._note("akshare_separate_distribution_legs", f"{symbol} {group.ex_date.iloc[0]}: same record date, distinct cash/bonus notices combined; latest notice gates visibility")
            else:
                result.append(group)  # Preserve ambiguous records for contract/conflict rejection.
        return pd.concat(result, ignore_index=True)

    def _fund_div(self, symbol):
        code, _ = symbol_parts(symbol)
        frames = []
        for year in range(int(self.start[:4]) - 1, int(self.end[:4]) + 1):
            raw = self._call("fund_fh_em", year=str(year), page=-1)
            require(raw, ["基金代码", "权益登记日", "除息日期", "分红", "分红发放日"], "fund_fh_em")
            if raw.empty:
                continue
            raw = raw[raw["基金代码"].astype(str).str.zfill(6) == code]
            frames.append(pd.DataFrame({"ts_code": symbol, "record_date": dates(raw["权益登记日"]), "ex_date": dates(raw["除息日期"]), "pay_date": dates(raw["分红发放日"]), "div_cash": numbers(raw, "分红"), "div_proc": "实施"}))
        self._note("akshare_fund_action_coverage", "Fund dividends are yuan/unit, no announcement dates; fund splits/conversions unavailable")
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
