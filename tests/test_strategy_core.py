from __future__ import annotations

from datetime import datetime

import pandas as pd

from all_weather_rotation_strategy.strategy import AllWeatherRotationBacktester


class FakeClient:
    def __init__(self) -> None:
        self._calendar = ["20260102", "20260105", "20260106", "20260107"]
        self._codes = ["600000.SH", "600036.SH", "000001.SZ", "000002.SZ"]

    def stock_basic(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "ts_code": self._codes,
                "name": ["浦发银行", "招商银行", "平安银行", "万科A"],
                "list_date": ["20000101", "20020101", "19980101", "19910101"],
                "market": ["主板", "主板", "主板", "主板"],
            }
        )

    def daily(self, ts_code: str, start_date: str, end_date: str, adj=None) -> pd.DataFrame:
        if ts_code == "000300.SH":
            return pd.DataFrame(
                {
                    "ts_code": [ts_code] * len(self._calendar),
                    "trade_date": self._calendar,
                    "open": [100, 101, 102, 103],
                    "high": [101, 102, 103, 104],
                    "low": [99, 100, 101, 102],
                    "close": [100, 101, 102, 103],
                    "pre_close": [99, 100, 101, 102],
                    "vol": [1, 1, 1, 1],
                    "amount": [1, 1, 1, 1],
                }
            )

        base = 10.0 if ts_code.endswith("SH") else 8.0
        return pd.DataFrame(
            {
                "ts_code": [ts_code] * len(self._calendar),
                "trade_date": self._calendar,
                "open": [base, base * 1.01, base * 1.02, base * 1.03],
                "high": [base * 1.02, base * 1.03, base * 1.04, base * 1.05],
                "low": [base * 0.98, base * 1.00, base * 1.01, base * 1.02],
                "close": [base, base * 1.02, base * 1.03, base * 1.04],
                "pre_close": [base * 0.99, base, base * 1.02, base * 1.03],
                "vol": [10000, 11000, 12000, 13000],
                "amount": [100000, 110000, 120000, 130000],
            }
        )

    def index_constituents(self, index_code: str, trade_date: str) -> list[str]:
        if index_code == "000300.SH":
            return ["600000.SH", "600036.SH"]
        return ["000001.SZ", "000002.SZ"]

    def daily_basic(self, ts_codes: list[str], trade_date: str) -> pd.DataFrame:
        rows = []
        for i, code in enumerate(ts_codes):
            rows.append(
                {
                    "ts_code": code,
                    "trade_date": trade_date,
                    "close": 10 + i,
                    "turnover_rate": 1.2,
                    "pe": 15 + i,
                    "pb": 2.0,
                    "ps": 3.0,
                    "eps": 0.6,
                    "total_mv": 6_000_000 + i * 10000,
                    "circ_mv": 5_000_000 + i * 10000,
                }
            )
        return pd.DataFrame(rows)

    def latest_fina_indicator(self, ts_code: str, trade_date: str) -> dict:
        return {
            "roe": 0.25,
            "roa": 0.16,
            "roic": 0.1,
            "netprofit_margin": 0.2,
            "grossprofit_margin": 0.35,
            "or_yoy": 30,
            "debt_to_assets": 40,
        }

    def latest_income(self, ts_code: str, trade_date: str) -> dict:
        return {
            "revenue": 1_000_000,
            "oper_cost": 700_000,
            "total_profit": 200_000,
            "n_income": 150_000,
            "non_oper_income": 10_000,
            "non_oper_exp": 2_000,
            "admin_exp": 50_000,
        }

    def latest_balance(self, ts_code: str, trade_date: str) -> dict:
        return {
            "total_assets": 10_000_000,
            "total_liab": 4_000_000,
            "undistr_porfit": 1_000_000,
            "inventories": 500_000,
            "total_share": 100_000,
        }

    def latest_cashflow(self, ts_code: str, trade_date: str) -> dict:
        return {"n_cashflow_act": 120_000, "ncfps": 0.8}


def test_backtester_runs_with_fake_client() -> None:
    client = FakeClient()
    bt = AllWeatherRotationBacktester(
        client=client,
        start_date="2026-01-01",
        end_date="2026-01-31",
        initial_capital=1_000_000,
    )

    trades, equity = bt.run()

    assert not equity.empty
    assert len(equity) == 4
    assert "equity" in equity.columns
    assert equity["equity"].iloc[-1] > 0
    assert isinstance(trades, pd.DataFrame)


def test_limit_rate_rules() -> None:
    assert AllWeatherRotationBacktester._limit_rate("300001.SZ", False) == 0.20
    assert AllWeatherRotationBacktester._limit_rate("688001.SH", False) == 0.20
    assert AllWeatherRotationBacktester._limit_rate("000001.SZ", True) == 0.05
    assert AllWeatherRotationBacktester._limit_rate("600000.SH", False) == 0.10
