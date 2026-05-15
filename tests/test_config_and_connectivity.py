from __future__ import annotations

import os

import pytest

from all_weather_rotation_strategy.config import TUSHARE_TOKEN
from all_weather_rotation_strategy.data_client import TinyshareClient


def test_token_present() -> None:
    assert isinstance(TUSHARE_TOKEN, str)
    assert len(TUSHARE_TOKEN.strip()) >= 32


@pytest.mark.skipif(
    os.getenv("RUN_LIVE_TINYSHARE_TESTS", "0") != "1",
    reason="需要设置 RUN_LIVE_TINYSHARE_TESTS=1 才执行在线连通测试",
)
def test_live_tinyshare_daily() -> None:
    client = TinyshareClient(token=TUSHARE_TOKEN, use_cache=False)
    df = client.daily(
        ts_code="000001.SZ",
        start_date="2026-01-01",
        end_date="2026-01-31",
        adj=None,
    )
    assert not df.empty
    assert "trade_date" in df.columns
    assert "close" in df.columns
