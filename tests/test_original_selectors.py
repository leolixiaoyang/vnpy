"""Exercise each original selector with other selector branches disabled."""
from types import SimpleNamespace

import pandas as pd
import pytest

from quantlab.models import AccountSnapshot
from quantlab.quality import QualityLog
from quantlab.strategies.all_weather_rotation import AllWeatherRotation


def chosen(overrides):
    row = {"ts_code": "600000.SH", "total_mv": 400e8, "circ_mv": 300e8, "pe": 10,
           "pe_ttm": 10, "ps_ttm": 2, "pb": 2, "pcf_net_ttm": 2,
           "eps_single": .5, "roe_pct": 1, "roa_pct": 1, "net_margin_pct": 1,
           "gross_margin_pct": 1, "revenue_growth_pct": 1,
           "total_revenue_growth_pct": 1, "op_growth_pct": 1,
           "retained_profit": 1000, "liability_equity": .1, "roic_ttm_ratio": .2}
    row.update(overrides)
    class Market:
        quality = QualityLog()
        def constituents(self, *args): return [row["ts_code"]]
        def eligible(self, codes, *args): return codes
        def fundamentals(self, *args): return pd.DataFrame([row])
        def bar(self, *args): return {"close": 10, "volume": 1000}
        def limits(self, *args): return 11, 9
    ctx = SimpleNamespace(date="2026-02-02", previous_date="2026-01-30", market=Market(), account=AccountSnapshot(100000, {}))
    strategy = AllWeatherRotation()
    strategy._strong = lambda pool, ascending, ctx: 1 if ascending else 2
    return strategy._targets(ctx)


def test_each_selector_can_select_independently():
    assert chosen({"total_mv": 950e8, "roic_ttm_ratio": 0}) == ["600000.SH"]  # BIG
    assert chosen({"pe": 31, "roic_ttm_ratio": 0}) == ["600000.SH"]  # BM
    assert chosen({"pe": 31, "pb": 11}) == ["600000.SH"]  # ROIC_BIG


@pytest.mark.parametrize("field,value", [("pe", 31), ("ps_ttm", 9), ("pcf_net_ttm", 11),
    ("eps_single", .3), ("roe_pct", .1), ("net_margin_pct", .1), ("gross_margin_pct", .3), ("revenue_growth_pct", .25)])
def test_big_original_filter_boundaries(field, value):
    assert chosen({"total_mv": 950e8, "roic_ttm_ratio": 0, field: value}) == []


@pytest.mark.parametrize("field,value", [("total_mv", 99e8), ("pb", 11), ("pcf_net_ttm", 4),
    ("eps_single", .3), ("roe_pct", .2), ("net_margin_pct", .1), ("revenue_growth_pct", .2), ("op_growth_pct", .1)])
def test_bm_original_filter_boundaries(field, value):
    assert chosen({"pe": 31, "roic_ttm_ratio": 0, field: value}) == []


@pytest.mark.parametrize("field,value", [("total_mv", 300e8), ("pe_ttm", 51), ("eps_single", .12),
    ("roa_pct", .15), ("liability_equity", .5), ("total_revenue_growth_pct", .3),
    ("revenue_growth_pct", .2), ("retained_profit", 0), ("roic_ttm_ratio", .08)])
def test_roic_original_filter_boundaries(field, value):
    assert chosen({"pe": 31, "pb": 11, field: value}) == []
