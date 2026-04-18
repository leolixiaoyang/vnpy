"""数据获取脚本 — 拉取信号和行情数据到本地。

运行方式：
    python fetch_data.py

输出：
    - signal parquet 文件：lab_data/ml_factor/signal/ml_factor_signal.parquet
    - 行情数据：AlphaLab（SQLite），路径 lab_data/ml_factor/
"""

from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path

import polars as pl
import tinyshare as ts

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import (  # noqa: E402
    CONTRACT_SETTINGS,
    END_DATE,
    INTERVAL,
    LAB_PATH,
    SIGNAL_CACHE,
    START_DATE,
    STOCK_POOL_MODE,
    STATIC_STOCK_POOL,
    TUSHARE_TOKEN,
    get_dynamic_stock_pool,
)
from signal_pipeline import MlFactorSignalPipeline, SignalConfig  # noqa: E402
from vnpy.alpha import AlphaLab  # noqa: E402
from vnpy.trader.constant import Exchange  # noqa: E402
from vnpy.trader.object import BarData  # noqa: E402


def _ts_to_vt_symbol(ts_code: str) -> str:
    return ts_code.replace(".SZ", ".SZSE").replace(".SH", ".SSE")


def fetch_signal() -> pl.DataFrame:
    """生成并保存 ML 因子信号。"""
    token = os.getenv("TUSHARE_TOKEN", TUSHARE_TOKEN)

    if STOCK_POOL_MODE == "dynamic":
        stock_pool = get_dynamic_stock_pool()
        print(f"使用动态股票池: {len(stock_pool)} 只")
    else:
        stock_pool = STATIC_STOCK_POOL
        print(f"使用固定股票池: {len(stock_pool)} 只")

    pipeline = MlFactorSignalPipeline(
        SignalConfig(
            ts_codes=stock_pool,
            start_date=START_DATE,
            end_date=END_DATE,
            token=token,
        )
    )
    signal_df = pipeline.generate()

    SIGNAL_CACHE.parent.mkdir(parents=True, exist_ok=True)
    signal_df.write_parquet(SIGNAL_CACHE)
    print(f"信号数据已保存: {SIGNAL_CACHE}")
    print(f"  形状: {signal_df.shape}")
    print(f"  列: {signal_df.columns}")
    return signal_df


def _download_daily_bars(ts_code: str, token: str) -> list[BarData]:
    ts.set_token(token)
    pro = ts.pro_api()

    is_fund = ts_code.startswith("51") or ts_code.startswith("15")

    if is_fund:
        raw = pro.fund_daily(
            ts_code=ts_code,
            start_date=START_DATE.replace("-", ""),
            end_date=END_DATE.replace("-", ""),
        )
    else:
        raw = pro.daily(
            ts_code=ts_code,
            start_date=START_DATE.replace("-", ""),
            end_date=END_DATE.replace("-", ""),
            adj="hfq",
        )
    if raw is None or len(raw) == 0:
        return []

    import pandas as pd
    if isinstance(raw, pd.DataFrame):
        df = pl.from_pandas(raw).sort("trade_date")
    else:
        df = pl.DataFrame(raw).sort("trade_date")

    vt_symbol = _ts_to_vt_symbol(ts_code)
    symbol, exchange_str = vt_symbol.split(".")
    exchange = Exchange[exchange_str]

    bars: list[BarData] = []
    for row in df.iter_rows(named=True):
        dt = datetime.strptime(str(row["trade_date"]), "%Y%m%d")
        bars.append(
            BarData(
                symbol=symbol,
                exchange=exchange,
                datetime=dt,
                interval=INTERVAL,
                open_price=float(row["open"]),
                high_price=float(row["high"]),
                low_price=float(row["low"]),
                close_price=float(row["close"]),
                volume=float(row.get("vol", 0)),
                turnover=float(row.get("amount", 0)),
                open_interest=0,
                gateway_name="DB",
            )
        )
    return bars


def fetch_bar_data(vt_symbols: list[str]) -> None:
    """下载并保存行情数据到 AlphaLab（跳过已存在的）。"""
    token = os.getenv("TUSHARE_TOKEN", TUSHARE_TOKEN)
    lab = AlphaLab(str(LAB_PATH))

    for vt_symbol in vt_symbols:
        existing = lab.load_bar_data(
            vt_symbol=vt_symbol,
            interval=INTERVAL,
            start=datetime.fromisoformat(START_DATE),
            end=datetime.fromisoformat(END_DATE),
        )
        if existing:
            print(f"  跳过 (已有数据): {vt_symbol}")
            continue

        ts_code = vt_symbol.replace(".SZSE", ".SZ").replace(".SSE", ".SH")
        print(f"  下载: {ts_code}")
        bars = _download_daily_bars(ts_code=ts_code, token=token)
        if not bars:
            print(f"    无数据")
            continue

        lab.save_bar_data(bars)
        print(f"    {len(bars)} 条")


def main():
    print("=" * 60)
    print("Step 1: 拉取信号数据")
    print("=" * 60)
    signal_df = fetch_signal()

    vt_symbols = list(signal_df["vt_symbol"].unique())
    print(f"\n回测标的: {len(vt_symbols)} 只")

    print("\n" + "=" * 60)
    print("Step 2: 拉取行情数据")
    print("=" * 60)
    fetch_bar_data(vt_symbols)

    print("\n" + "=" * 60)
    print("完成")
    print("=" * 60)


if __name__ == "__main__":
    main()
