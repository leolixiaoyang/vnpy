import pandas as pd
import pytest

from quantlab.data.bundle import DataBundle
from quantlab.data.cache import QueryCache
from quantlab.data.normalization import normalize
from quantlab.data.provider import TushareProvider
from quantlab.data.schemas import validate_request
from quantlab.data.transports import ProviderError, SDKTransport
from quantlab.data.view import MarketDataView
from quantlab.quality import ApproximationError, DataError, QualityLog


@pytest.mark.parametrize("api,params,fields", [
    ("daily", {"adj": "hfq"}, ("close",)),
    ("daily_basic", {}, ("eps",)),
    ("daily", {"start_date": "2026-01-01"}, ("close",)),
])
def test_invalid_contract_rejected_before_network(api, params, fields):
    with pytest.raises(DataError):
        validate_request(api, params, fields)


def test_explicit_units_not_name_based():
    daily = normalize("daily", pd.DataFrame([{"ts_code": "600000.SH", "trade_date": "20260101", "close": "10", "vol": "2", "amount": "3"}]))
    assert daily.volume.iloc[0] == 200 and daily.amount.iloc[0] == 3000
    basic = normalize("daily_basic", pd.DataFrame([{"ts_code": "600000.SH", "trade_date": "20260101", "total_mv": 2, "circ_mv": 1, "total_share": 3}]))
    assert basic.total_mv.iloc[0] == 20000 and basic.total_share.iloc[0] == 30000
    balance = normalize("balancesheet", pd.DataFrame([{"ts_code": "600000.SH", "ann_date": "20260401", "end_date": "20251231", "total_share": 3}]))
    assert balance.total_share.iloc[0] == 3


def test_conflicting_duplicates_invalid_numeric_fail():
    rows = pd.DataFrame([{"ts_code": "600000.SH", "trade_date": "20260101", "close": 10}, {"ts_code": "600000.SH", "trade_date": "20260101", "close": 11}])
    with pytest.raises(DataError, match="conflicting"):
        normalize("daily", rows)
    rows["close"] = rows["close"].astype(object)
    rows.loc[0, "close"] = "bad"
    with pytest.raises(DataError, match="numeric"):
        normalize("daily", rows)


def test_dataframe_contract_and_error_redaction():
    class Client:
        def query(self, *a, **k):
            raise RuntimeError("2002 token=DO_NOT_LEAK 权限不足")
    with pytest.raises(ProviderError) as caught:
        SDKTransport(client=Client()).query("daily", {}, ("close",))
    assert "DO_NOT_LEAK" not in str(caught.value) and caught.value.kind == "permission_or_auth"
    class BadClient:
        def query(self, *a, **k):
            return []
    with pytest.raises(DataError, match="DataFrame"):
        SDKTransport(client=BadClient()).query("daily", {}, ("close",))


def test_covering_cache_and_offline_never_calls_network(tmp_path):
    class Client:
        calls = 0
        def query(self, *args):
            self.calls += 1
            return pd.DataFrame([{"ts_code": "600000.SH", "trade_date": d, "close": 10} for d in ["20260101", "20260102", "20260103"]])
    client = Client()
    cache = QueryCache(tmp_path)
    fields = ("ts_code", "trade_date", "close")
    provider = TushareProvider(client, cache)
    provider.fetch("daily", {"start_date": "20260101", "end_date": "20260103"}, fields)
    offline = TushareProvider(None, cache, offline=True)
    df = offline.fetch("daily", {"start_date": "20260102", "end_date": "20260102"}, fields)
    assert len(df) == 1 and client.calls == 1
    with pytest.raises(DataError, match="offline"):
        offline.fetch("fund_daily", {}, fields)


def test_row_cap_splits_dates_and_refuses_unsplittable(monkeypatch):
    from quantlab.data import schemas
    from dataclasses import replace
    monkeypatch.setitem(schemas.SCHEMAS, "daily", replace(schemas.SCHEMAS["daily"], cap=2))
    class Client:
        def query(self, api, params, fields):
            dates = pd.date_range(params["start_date"], params["end_date"]).strftime("%Y%m%d")
            return pd.DataFrame([{"ts_code": "600000.SH", "trade_date": d, "close": 10} for d in dates[:2]])
    df = TushareProvider(Client()).fetch("daily", {"start_date": "20260101", "end_date": "20260104"})
    assert len(df) == 4


def test_announced_not_report_period_and_future_revision(bundle):
    bundle.tables["income"] = pd.DataFrame([
        {"ts_code": "600000.SH", "ann_date": "2026-02-01", "f_ann_date": "2026-02-03", "end_date": "2025-12-31", "report_type": "1", "revenue": 10},
        {"ts_code": "600000.SH", "ann_date": "2026-04-01", "f_ann_date": "2026-04-01", "end_date": "2025-12-31", "report_type": "1", "revenue": 20}])
    view = MarketDataView(bundle, "2026-02-04")
    assert view.financial_rows("income", "600000.SH", "2026-02-03").empty
    assert view.financial_rows("income", "600000.SH", "2026-02-04").revenue.iloc[-1] == 10
    with pytest.raises(DataError, match="Future"):
        view.bar("600000.SH", "2026-02-05")


def test_ps_pcf_roa_and_threshold_mapping(bundle):
    symbol = "600000.SH"
    bundle.tables["cashflow"] = pd.DataFrame([
        {"ts_code": symbol, "ann_date": "2025-04-01", "end_date": "2024-12-31", "n_incr_cash_cash_equ": 10e8, "n_cashflow_act": 99e8},
        {"ts_code": symbol, "ann_date": "2024-10-20", "end_date": "2024-09-30", "n_incr_cash_cash_equ": 4e8, "n_cashflow_act": 99e8},
        {"ts_code": symbol, "ann_date": "2025-10-20", "end_date": "2025-09-30", "n_incr_cash_cash_equ": 6e8, "n_cashflow_act": 99e8}])
    bundle.tables["fina_indicator"]["roa"] = 999
    bundle.tables["daily_basic"]["ps"] = 999
    view = MarketDataView(bundle, "2026-02-02")
    snap = view.fundamentals([symbol], "2026-01-30").iloc[0]
    assert snap.pcf_net_ttm == pytest.approx(10e8 / 12e8)
    assert snap.roa_pct == 1.0 and snap.ps_ttm == 2.0
    assert snap.roe_pct == 2.0  # percentage points, not 0.02


def test_bundle_checksum_and_strict_mode(bundle, tmp_path):
    bundle.save(tmp_path)
    loaded = DataBundle.load(tmp_path)
    assert loaded.metadata["snapshot_id"]
    with pytest.raises(ApproximationError):
        loaded.preflight("2026-01-15", "2026-02-10", QualityLog(strict=True))
    target = tmp_path / "daily.parquet"
    target.write_bytes(target.read_bytes() + b"bad")
    with pytest.raises(DataError, match="checksum"):
        DataBundle.load(tmp_path)


def test_partial_adjustment_does_not_mix_price_scales(bundle):
    factors = bundle.tables["adj_factor"]
    factors.loc[factors.ts_code == "600000.SH", "adj_factor"] = 10
    factors.loc[(factors.ts_code == "600000.SH") & (factors.trade_date == "2026-01-30"), "adj_factor"] = float("nan")
    view = MarketDataView(bundle, "2026-02-02")
    raw = view.bars("600000.SH", "2026-01-30", 10)
    adjusted = view.bars("600000.SH", "2026-01-30", 10, adjusted=True)
    assert adjusted.close.tolist() == raw.close.tolist()
    assert any(e.code == "missing_adjustment" for e in view.quality.events)
