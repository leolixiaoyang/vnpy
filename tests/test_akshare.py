from collections import Counter

import pandas as pd
import pytest

from quantlab.cli import main, provider_for
from quantlab.config import load_config
from quantlab.data.akshare import AKShareTransport
from quantlab.data.bundle import DataBundle
from quantlab.data.cache import QueryCache
from quantlab.data.provider import TushareProvider
from quantlab.data.transports import ProviderError
from quantlab.data.view import MarketDataView
from quantlab.quality import ApproximationError, DataError, QualityLog


class FakeSDK:
    def __init__(self, **responses):
        self.responses, self.calls = responses, []

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)

        def call(**kwargs):
            self.calls.append((name, kwargs))
            response = self.responses[name]
            if callable(response):
                response = response(**kwargs)
            if isinstance(response, Exception):
                raise response
            return response.copy()
        return call


def client(**responses):
    transport = AKShareTransport(client=FakeSDK(**responses), start="2026-01-01", end="2026-04-30")
    return TushareProvider(transport, quality=transport.quality)


def em_bars():
    return pd.DataFrame({"日期": ["2026-01-29", "2026-01-30"], "开盘": [10., 11.], "收盘": [11., 12.],
                         "最高": [11., 12.], "最低": [10., 11.], "成交量": [10, 20],
                         "成交额": [11000., 24000.], "涨跌额": [1., 1.]})


@pytest.mark.parametrize("api,symbol,fn", [("daily", "600000.SH", "stock_zh_a_hist"),
    ("fund_daily", "518880.SH", "fund_etf_hist_em"), ("fund_daily", "164824.SZ", "fund_lof_hist_em")])
def test_bar_units_and_lof_routing(api, symbol, fn):
    p = client(**{fn: em_bars()})
    frame = p.fetch(api, {"ts_code": symbol, "start_date": "2026-01-30", "end_date": "2026-01-30"})
    assert frame.trade_date.tolist() == ["2026-01-30"]
    assert frame.volume.iloc[0] == 2000
    assert frame.amount.iloc[0] == 24000
    assert frame.pre_close.iloc[0] == 11
    assert p.transport.client.calls[0][1]["symbol"] == symbol[:6]


def test_sina_fallback_preclose_units_and_error_redaction():
    raw = pd.DataFrame({"date": ["2026-01-29", "2026-01-30"], "open": [10, 11], "high": [11, 12],
                        "low": [10, 11], "close": [11, 12], "volume": [1000, 2000], "amount": [11000, 24000]})
    p = client(fund_etf_hist_em=RuntimeError("secret_token"), fund_etf_hist_sina=raw)
    frame = p.fetch("fund_daily", {"ts_code": "518880.SH", "trade_date": "20260130"})
    assert frame.volume.iloc[0] == 2000 and frame.amount.iloc[0] == 24000
    assert frame.pre_close.iloc[0] == 11
    assert p.transport.client.calls[-1][1] == {"symbol": "sh518880"}
    assert "akshare_price_source_fallback" in {e.code for e in p.quality.events}
    assert "secret_token" not in str(p.quality.export())
    with pytest.raises(ProviderError, match="adjusted_prices_unavailable"):
        p.fetch("fund_adj", {"ts_code": "518880.SH"})


@pytest.mark.parametrize("amount,volume", [(None, None), (1100000, 100000)])
def test_sina_fund_volume_ambiguity_or_lot_unit(amount, volume):
    raw = pd.DataFrame({"date": ["2026-01-30"], "open": [11], "high": [11],
                        "low": [11], "close": [11], "volume": [1000], "amount": [amount]})
    p = client(fund_etf_hist_em=RuntimeError(), fund_etf_hist_sina=raw)
    frame = p.fetch("fund_daily", {"ts_code": "518880.SH"})
    assert pd.isna(frame.volume.iloc[0]) if volume is None else frame.volume.iloc[0] == volume


def test_bad_contract_does_not_trigger_fallback():
    p = client(stock_zh_a_hist=pd.DataFrame({"wrong": [1]}))
    with pytest.raises(DataError, match="missing columns"):
        p.fetch("daily", {"ts_code": "600000.SH"})
    assert len(p.transport.client.calls) == 1


def test_hfq_factors_do_not_change_raw_prices():
    def bars(**kwargs):
        df = em_bars()
        if kwargs["adjust"] == "hfq":
            df["收盘"] *= 2
        return df
    p = client(stock_zh_a_hist=bars)
    factors = p.fetch("adj_factor", {"ts_code": "600000.SH"})
    prices = p.fetch("daily", {"ts_code": "600000.SH"})
    assert factors.adj_factor.tolist() == [2, 2]
    assert prices.close.tolist() == [11, 12]
    assert len(p.transport.client.calls) == 2


def valuations():
    return pd.DataFrame({"数据日期": ["2026-01-29", "2026-01-30"], "总市值": [2e9, 3e9],
                        "流通市值": [1e9, 2e9], "总股本": [2e8, 2e8], "流通股本": [1e8, 1e8],
                        "当日收盘价": [10, 15], "PE(静)": [10, 15], "PE(TTM)": [9, 14],
                        "市净率": [1, 2], "市销率": [3, 4], "市现率": [999, 999]})


def test_valuation_yuan_shares_ps_ttm_missing_dates_and_memoization():
    p = client(stock_value_em=valuations())
    for day in ["20260129", "20260130"]:
        frame = p.fetch("daily_basic", {"ts_code": "600000.SH", "trade_date": day})
    assert frame.total_mv.iloc[0] == 3e9 and frame.circ_mv.iloc[0] == 2e9
    assert frame.total_share.iloc[0] == 2e8 and frame.float_share.iloc[0] == 1e8
    assert frame.ps_ttm.iloc[0] == 4 and frame.ps.isna().all()
    assert "市现率" not in frame and "pcf_net_ttm" not in frame
    assert p.fetch("daily_basic", {"ts_code": "600000.SH", "trade_date": "20260128"}).empty
    assert len(p.transport.client.calls) == 1
    with pytest.raises(DataError, match="requires ts_code"):
        p.fetch("daily_basic", {"trade_date": "20260130"})


def test_calendar_previous_session_and_coverage():
    p = client(tool_trade_date_hist_sina=pd.DataFrame({"trade_date": ["2026-01-09", "2026-01-12", "2026-01-13"]}))
    frame = p.fetch("trade_cal", {"exchange": "SSE", "start_date": "20260110", "end_date": "20260113"})
    assert frame.is_open.tolist() == [0, 0, 1, 1]
    assert frame.pretrade_date.tolist() == ["2026-01-09", "2026-01-09", "2026-01-09", "2026-01-12"]
    with pytest.raises(DataError, match="does not cover"):
        p.fetch("trade_cal", {"start_date": "20260110", "end_date": "20260114"})


def test_constituents_are_not_backfilled_to_old_dates():
    p = client(index_stock_cons_weight_csindex=pd.DataFrame({"日期": ["2026-09-30"], "成分券代码": ["600000"], "权重": [1.2]}))
    assert p.fetch("index_weight", {"index_code": "000300.SH", "start_date": "20180101", "end_date": "20260430"}).empty
    frame = p.fetch("index_weight", {"index_code": "000300.SH", "trade_date": "20260930"})
    assert frame.con_code.tolist() == ["600000.SH"]
    assert "akshare_constituent_history_incomplete" in {e.code for e in p.quality.events}


def financial_sdk():
    def indicators(**kwargs):
        if kwargs["indicator"] == "按单季度":
            return pd.DataFrame({"REPORT_DATE": ["2025-06-30"], "EPSJB": [.5], "ROE_DILUTED": [2.5],
                                 "JROA": [1.1], "NET_PROFIT_RATIO": [11], "GROSS_PROFIT_RATIO": [30], "TOTALOPERATEREVETZ": [20]})
        return pd.DataFrame({"REPORT_DATE": ["2025-06-30"], "NOTICE_DATE": ["2025-08-20"],
                             "EPSJB": [1.2], "ROEJQ": [6.1], "ZZCJLL": [3], "ROIC": [8]})
    income = pd.DataFrame({"REPORT_DATE": ["2024-03-31", "2024-06-30", "2025-03-31", "2025-06-30"],
                          "NOTICE_DATE": ["2024-04-20", "2024-08-20", "2025-04-20", "2025-08-25"],
                          "OPERATE_INCOME": [100, 300, 120, 360], "OPERATE_PROFIT": [10, 30, 12, 36]})
    balance = pd.DataFrame({"REPORT_DATE": ["2025-06-30"], "NOTICE_DATE": ["2025-08-20"], "TOTAL_ASSETS": [1000],
                           "TOTAL_LIABILITIES": [200], "TOTAL_EQUITY": [800], "UNASSIGN_RPOFIT": [50]})
    cash = pd.DataFrame({"REPORT_DATE": ["2024-06-30", "2024-12-31", "2025-06-30"],
                        "NOTICE_DATE": ["2024-08-20", "2025-03-20", "2025-08-20"],
                        "NETCASH_OPERATE": [999, 999, 999], "CCE_ADD": [-10, -20, -15]})
    return FakeSDK(stock_financial_analysis_indicator_em=indicators, stock_profit_sheet_by_report_em=income,
                   stock_balance_sheet_by_report_em=balance, stock_cash_flow_sheet_by_report_em=cash)


def test_financial_quarter_mapping_growth_units_and_publication_gate():
    transport = AKShareTransport(client=financial_sdk())
    p = TushareProvider(transport, quality=transport.quality)
    fin = p.fetch("fina_indicator", {"ts_code": "600000.SH", "start_date": "20250101", "end_date": "20251231"})
    assert fin.q_eps.iloc[0] == .5 and fin.eps.iloc[0] == 1.2
    assert fin.q_roe.iloc[0] == 2.5 and fin.q_npta.iloc[0] == 1.1
    assert fin.q_sales_yoy.iloc[0] == 20 and fin.q_op_yoy.iloc[0] == 20
    assert fin.ann_date.iloc[0] == "2025-08-25"  # latest input publication, not report end
    tables = {api: p.fetch(api, {"ts_code": "600000.SH"}) for api in ["balancesheet", "cashflow"]}
    tables["fina_indicator"] = fin
    tables["daily_basic"] = pd.DataFrame([{"ts_code": "600000.SH", "trade_date": "2025-08-26", "total_mv": 1000}])
    view = MarketDataView(DataBundle(tables), "2025-08-26")
    assert view.financial_rows("fina_indicator", "600000.SH", "2025-08-25").empty
    f = view.fundamentals(["600000.SH"]).iloc[0]
    assert f.pcf_net_ttm == -40  # 1000 / (-15 + -20 - -10), NOT operating cash flow
    assert f.retained_profit == 50 and f.liability_equity == .25
    assert f.roic_ttm_ratio == .08
    assert transport.client.calls[0][1]["symbol"] == "600000.SH"
    assert any(kwargs.get("symbol") == "SH600000" for _, kwargs in transport.client.calls)


def test_missing_announcements_are_excluded_not_replaced_by_period_end():
    raw = pd.DataFrame({"REPORT_DATE": ["2025-06-30"], "NOTICE_DATE": [None], "CCE_ADD": [1]})
    p = client(stock_cash_flow_sheet_by_report_em=raw)
    assert p.fetch("cashflow", {"ts_code": "600000.SH"}).empty
    assert "akshare_missing_announcement" in {e.code for e in p.quality.events}


def test_invalid_required_dates_raise_even_if_outside_the_filter_window():
    raw = valuations()
    raw.loc[0, "数据日期"] = "invalid"
    p = client(stock_value_em=raw)
    with pytest.raises(DataError, match="missing required values in trade_date"):
        p.fetch("daily_basic", {"ts_code": "600000.SH", "trade_date": "20260130"})


def test_cash_equivalent_balance_difference_fallback():
    raw = pd.DataFrame({"REPORT_DATE": ["2025-06-30"], "NOTICE_DATE": ["2025-08-20"], "END_CCE": [80], "BEGIN_CCE": [100]})
    p = client(stock_cash_flow_sheet_by_report_em=raw)
    assert p.fetch("cashflow", {"ts_code": "600000.SH"}).n_incr_cash_cash_equ.iloc[0] == -20


def test_stock_and_fund_distribution_units_and_year_memoization():
    stocks = pd.DataFrame({"实施方案公告日期": ["2026-01-01"], "股权登记日": ["2026-01-09"],
                           "除权日": ["2026-01-12"], "送股比例": [2.], "转增比例": [1.], "派息比例": [5.]})
    funds = pd.DataFrame({"基金代码": ["518880"], "权益登记日": ["2026-01-09"], "除息日期": ["2026-01-12"],
                          "分红": [.15], "分红发放日": ["2026-01-15"]})
    p = client(stock_dividend_cninfo=stocks, fund_fh_em=lambda **kw: funds if kw["year"] == "2026" else funds.iloc[:0])
    stock = p.fetch("dividend", {"ts_code": "600000.SH"}).iloc[0]
    assert stock.cash_div_tax == .5 and stock.stk_div == .3
    fund = p.fetch("fund_div", {"ts_code": "518880.SH"}).iloc[0]
    assert fund.div_cash == .15 and pd.isna(fund.ann_date)
    p.fetch("fund_div", {"ts_code": "513100.SH"})
    assert Counter(n for n, _ in p.transport.client.calls)["fund_fh_em"] == 2


def test_bonus_not_lost_when_other_bonus_component_is_null():
    stocks = pd.DataFrame({"实施方案公告日期": ["2026-01-01"], "股权登记日": ["2026-01-09"],
                           "除权日": ["2026-01-12"], "送股比例": [3.], "转增比例": [None], "派息比例": [None]})
    p = client(stock_dividend_cninfo=stocks)
    assert p.fetch("dividend", {"ts_code": "600000.SH"}).stk_div.iloc[0] == .3


def test_cninfo_cash_and_bonus_notices_with_same_record_date_are_combined():
    rows = pd.DataFrame({"实施方案公告日期": ["2006-05-15", "2006-05-17"], "股权登记日": ["2006-05-18"] * 2,
                         "除权日": ["2006-05-19"] * 2, "派息日": ["2006-05-23", None],
                         "股份到账日": [None, "2006-05-19"], "送股比例": [None, 10.],
                         "转增比例": [None, 0.], "派息比例": [3., 0.]})
    p = client(stock_dividend_cninfo=rows)
    frame = p.fetch("dividend", {"ts_code": "600519.SH"})
    assert len(frame) == 1
    row = frame.iloc[0]
    assert row.cash_div_tax == .3 and row.stk_div == 1
    assert row.ann_date == "2006-05-17" and row.pay_date == "2006-05-23" and row.div_listdate == "2006-05-19"


def test_ambiguous_cash_notices_are_rejected_instead_of_summed():
    from quantlab.data.prepare import corporate_table
    rows = pd.DataFrame({"实施方案公告日期": ["2026-01-01", "2026-01-02"], "股权登记日": ["2026-01-09"] * 2,
                         "除权日": ["2026-01-12"] * 2, "送股比例": [0., 0.], "转增比例": [0., 0.], "派息比例": [3., 4.]})
    p = client(stock_dividend_cninfo=rows)
    raw = p.fetch("dividend", {"ts_code": "600519.SH"})
    with pytest.raises(DataError, match="Conflicting"):
        corporate_table({"dividend": raw}, p.quality)


def test_metadata_leading_zero_listing_dates_and_gaps():
    p = client(stock_info_sh_name_code=pd.DataFrame({"证券代码": [600000], "证券简称": ["浦发"], "上市日期": ["1999-11-10"]}),
               stock_info_sz_name_code=pd.DataFrame({"A股代码": [1], "A股简称": ["平安"], "A股上市日期": ["1991-04-03"]}),
               fund_name_em=pd.DataFrame({"基金代码": ["164824"], "基金简称": ["印度LOF"], "基金类型": ["QDII"]}))
    frame = p.fetch("stock_basic", {"list_status": "L"})
    assert set(frame.ts_code) == {"600000.SH", "000001.SZ"}
    assert frame.list_date.min() == "1991-04-03"
    assert p.fetch("stock_basic", {"list_status": "D"}).empty
    fund = p.fetch("fund_basic", {"ts_code": "164824.SZ", "market": "E"})
    assert fund.ts_code.tolist() == ["164824.SZ"] and fund.list_date.isna().all()
    assert p.optional("stk_limit", {"trade_date": "20260130"}).empty
    assert p.optional("namechange", {"ts_code": "600000.SH"}).empty


def test_scoped_listing_metadata_does_not_need_bulk_exchange_endpoints():
    p = client(stock_profile_cninfo=pd.DataFrame({"A股代码": ["000001"], "A股简称": ["平安银行"], "上市日期": ["1991-04-03"]}))
    frame = p.fetch("stock_basic", {"ts_code": "000001.SZ", "list_status": "L"})
    assert frame.ts_code.tolist() == ["000001.SZ"] and frame.list_date.iloc[0] == "1991-04-03"
    assert p.transport.client.calls == [("stock_profile_cninfo", {"symbol": "000001"})]


def test_cached_quality_is_replayed_and_strict_rejects_approximation(tmp_path):
    first = client(stock_value_em=valuations())
    first.cache = QueryCache(tmp_path, "akshare-test")
    request = {"ts_code": "600000.SH", "trade_date": "20260130"}
    first.fetch("daily_basic", request)
    second = TushareProvider(cache=first.cache, offline=True)
    second.fetch("daily_basic", request)
    assert second.quality.export() == first.quality.export()
    strict = TushareProvider(cache=first.cache, offline=True, quality=QualityLog(strict=True))
    with pytest.raises(ApproximationError, match="akshare_valuation_coverage"):
        strict.fetch("daily_basic", request)


def test_config_default_factory_and_provider_override(tmp_path, monkeypatch, capsys):
    path = tmp_path / "config.toml"
    path.write_text('[data]\nsnapshot="data"\n[backtest]\nstart="2026-01-01"\nend="2026-04-30"\n')
    config = load_config(path)
    assert config["data"]["provider"] == "akshare"
    import quantlab.data.akshare as adapter
    fake = FakeSDK()
    monkeypatch.setattr(adapter.importlib, "import_module", lambda _: fake)
    assert provider_for(config).transport.client is fake
    assert main(["doctor"]) == 0
    import json
    report = json.loads(capsys.readouterr().out)
    assert report["provider"] == "akshare" and not report["credentials_required"]
    assert report["credential_env"] is None and not report["online_verified"]
    path.write_text(path.read_text().replace('[data]', '[data]\nprovider="unknown"'))
    with pytest.raises(DataError, match="data.provider"):
        load_config(path)


@pytest.mark.parametrize("selected", ["akshare", "tushare", "tinyshare"])
def test_cli_prepare_provider_override_is_explicit_and_does_not_edit_config(selected, tmp_path, monkeypatch, capsys):
    import quantlab.cli as cli
    path = tmp_path / "config.toml"
    original = '[data]\nsnapshot="data"\n[backtest]\nstart="2026-01-01"\nend="2026-04-30"\n'
    path.write_text(original)
    seen = []
    monkeypatch.setattr(cli, "provider_for", lambda config: seen.append(config["data"]["provider"]))
    monkeypatch.setattr(cli, "prepare", lambda provider, config: DataBundle(metadata={"provider": config["data"]["provider"]}))
    assert main(["data", "prepare", "--config", str(path), "--provider", selected]) == 0
    assert seen == [selected]
    assert path.read_text() == original
    assert DataBundle.load(tmp_path / "data").metadata["provider"] == selected
