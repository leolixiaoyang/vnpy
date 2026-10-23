"""Preparation integration uses fake *raw Tushare* responses, not normalized tables."""
import pandas as pd

from quantlab.data.prepare import prepare
from quantlab.data.provider import TushareProvider
from quantlab.demo import demo_bundle


class RawProviderFixture:
    provider = "fixture"
    version = "1"

    def __init__(self):
        self.bundle = demo_bundle()
        self.calls = []

    def query(self, api, params, fields):
        self.calls.append((api, params.copy()))
        df = self.bundle.table(api)
        if api == "stock_basic" and params.get("list_status") != "L":
            df = pd.DataFrame()
        if api == "index_basic":
            df = pd.DataFrame([{"ts_code": params["ts_code"], "name": "fixture", "market": "CSI", "publisher": "fixture"}])
        if "ts_code" in params and "ts_code" in df:
            df = df[df.ts_code == params["ts_code"]]
        if "index_code" in params and "index_code" in df:
            df = df[df.index_code == params["index_code"]]
        if "trade_date" in params and "trade_date" in df:
            df = df[df.trade_date.str.replace("-", "") == params["trade_date"]]
        if "start_date" in params:
            axis = "end_date" if api == "fina_indicator" else "cal_date" if api == "trade_cal" else "trade_date"
            if axis in df:
                vals = df[axis].str.replace("-", "")
                df = df[vals.between(params["start_date"], params["end_date"])]
        df = df.copy()
        # Convert the fixture back to raw units before the real normalization layer.
        if api == "daily_basic":
            for col in ["total_mv", "circ_mv"]:
                if col in df:
                    df[col] /= 10000
        if "volume" in df:
            df["vol"] = df.pop("volume") / 100
        return df.reindex(columns=fields)


def test_prepare_constituent_union_data_units_and_monthly_valuations():
    transport = RawProviderFixture()
    config = {"backtest": {"start": "2026-01-15", "end": "2026-02-10"},
              "strategy": {"parameters": {"funds": []}}, "fallback_pools": {}}
    bundle = prepare(TushareProvider(transport), config)
    assert set(bundle.tables["daily"].ts_code) == {"600000.SH", "600036.SH", "000001.SZ", "000002.SZ"}
    assert bundle.tables["daily"].volume.iloc[0] == 100000
    assert bundle.tables["daily_basic"].total_mv.min() == 10e8
    valuation_calls = [params for api, params in transport.calls if api == "daily_basic"]
    assert valuation_calls == [{"trade_date": "20260130"}]
    assert bundle.metadata["provider"] == "fixture"


def test_prepare_symbol_scoped_valuations_and_unsupported_limits():
    transport = RawProviderFixture()
    transport.valuation_by_symbol = True
    transport.metadata_by_symbol = True
    transport.historical_limits = False
    transport.mapping_version = "akshare-fixture"
    config = {"backtest": {"start": "2026-01-15", "end": "2026-02-10"},
              "strategy": {"parameters": {"funds": []}}, "fallback_pools": {}}
    bundle = prepare(TushareProvider(transport), config)
    calls = [params for api, params in transport.calls if api == "daily_basic"]
    assert len(calls) == 4
    assert {p["ts_code"] for p in calls} == set(bundle.tables["daily"].ts_code)
    assert all(p["trade_date"] == "20260130" for p in calls)
    metadata_calls = [params for api, params in transport.calls if api == "stock_basic"]
    assert len(metadata_calls) == 4 and all("ts_code" in p for p in metadata_calls)
    assert not any(api == "stk_limit" for api, _ in transport.calls)
    assert bundle.metadata["mapping_version"] == "akshare-fixture"
    assert any(e["code"] == "provider_unavailable" for e in bundle.metadata["quality"])
