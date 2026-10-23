import pandas as pd

from quantlab.data.normalization import normalize
from quantlab.data.prepare import corporate_table
from quantlab.quality import QualityLog


def test_fund_dividend_is_per_share_not_per_ten():
    raw = pd.DataFrame([{"ts_code": "164824.SZ", "ann_date": "20260101", "record_date": "20260105",
                         "ex_date": "20260106", "pay_date": "20260108", "div_proc": "实施", "div_cash": .017}])
    result = corporate_table({"fund_div": normalize("fund_div", raw)}, QualityLog())
    assert result.cash_per_share.iloc[0] == .017


def test_dividend_proposals_do_not_fail_or_accrue():
    raw = pd.DataFrame([
        {"ts_code": "600000.SH", "ann_date": "20260101", "end_date": "20251231", "record_date": None, "ex_date": None, "div_proc": "预案", "cash_div_tax": .1},
        {"ts_code": "600000.SH", "ann_date": "20260120", "end_date": "20251231", "record_date": "20260125", "ex_date": "20260126", "div_proc": "实施", "cash_div_tax": .1}])
    result = corporate_table({"dividend": normalize("dividend", raw)}, QualityLog())
    assert len(result) == 1 and result.cash_per_share.iloc[0] == .1
