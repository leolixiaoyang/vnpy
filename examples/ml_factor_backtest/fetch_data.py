"""数据获取脚本 — 拉取信号和行情数据到本地。

运行方式：
    python fetch_data.py                    # 分批跑全部 1000 只
    python fetch_data.py --batch 000012.SZ  # 只跑指定股票

输出：
    - signal parquet：lab_data/ml_factor/signal/ml_factor_signal.parquet
    - 行情数据：AlphaLab（SQLite），路径 lab_data/ml_factor/

设计要点：
    1. 股票间 sleep(0.5s)，控制 API 频率
    2. 分批处理（默认 100 只/批），每批跑完立即保存信号
"""

from __future__ import annotations

import os
import sys
import time
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

# 每批股票数量
BATCH_SIZE: int = 100
# 股票间 sleep 秒数
SLEEP_SECONDS: float = 0.5


def _ts_to_vt_symbol(ts_code: str) -> str:
    return ts_code.replace(".SZ", ".SZSE").replace(".SH", ".SSE")


def _fetch_single_batch(ts_codes: list[str], token: str) -> pl.DataFrame:
    """跑一批股票的信号管线，返回合并后的 signal_df。"""
    batch_frames: list[pl.DataFrame] = []

    for i, ts_code in enumerate(ts_codes):
        print(f"  [{i+1}/{len(ts_codes)}] {ts_code}", end=" ... ", flush=True)

        pipeline = MlFactorSignalPipeline(
            SignalConfig(
                ts_codes=[ts_code],
                start_date=START_DATE,
                end_date=END_DATE,
                token=token,
            )
        )

        try:
            df = pipeline.generate()
        except Exception as e:
            print(f"ERROR ({e})")
            if SLEEP_SECONDS > 0:
                time.sleep(SLEEP_SECONDS)
            continue

        if df.is_empty():
            print("EMPTY")
        else:
            print(f"{df.shape}")
            batch_frames.append(df)

        if SLEEP_SECONDS > 0:
            time.sleep(SLEEP_SECONDS)

    if batch_frames:
        return pl.concat(batch_frames, how="vertical")
    return pl.DataFrame()


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


def fetch_signal_batched(ts_codes: list[str], token: str) -> pl.DataFrame:
    """分批拉取信号数据，每批保存。"""
    SIGNAL_CACHE.parent.mkdir(parents=True, exist_ok=True)

    # 如果已存在缓存，尝试加载已有数据，跳过已跑过的股票
    existing_codes: set[str] = set()
    if SIGNAL_CACHE.exists():
        try:
            existing = pl.read_parquet(SIGNAL_CACHE)
            if not existing.is_empty() and "vt_symbol" in existing.columns:
                existing_codes = set(existing["vt_symbol"].unique())
                print(f"  已有 {len(existing_codes)} 只股票的数据")
        except Exception:
            pass

    # 过滤掉已跑过的
    remaining = [c for c in ts_codes if _ts_to_vt_symbol(c) not in existing_codes]
    total_remaining = len(remaining)
    if total_remaining == 0:
        print("  所有股票数据已存在，跳过信号拉取")
        return pl.read_parquet(SIGNAL_CACHE)
    print(f"  还需处理: {total_remaining} 只")

    # 分批处理
    batches = [remaining[i:i+BATCH_SIZE] for i in range(0, total_remaining, BATCH_SIZE)]

    for batch_idx, batch_codes in enumerate(batches):
        print(f"\n批次 {batch_idx+1}/{len(batches)}: {len(batch_codes)} 只股票")
        batch_df = _fetch_single_batch(batch_codes, token)

        if batch_df.is_empty():
            print(f"  批次 {batch_idx+1} 无数据，跳过")
            continue

        # 合并已有数据 + 新批次数据，覆盖保存
        if SIGNAL_CACHE.exists():
            existing_df = pl.read_parquet(SIGNAL_CACHE)
            combined = pl.concat([existing_df, batch_df], how="vertical")
        else:
            combined = batch_df
        combined.write_parquet(SIGNAL_CACHE)
        print(f"  批次 {batch_idx+1} 已保存，累计: {combined.shape}")

    # 最终读取
    return pl.read_parquet(SIGNAL_CACHE)


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
            continue

        ts_code = vt_symbol.replace(".SZSE", ".SZ").replace(".SSE", ".SH")
        print(f"  下载: {ts_code}")
        bars = _download_daily_bars(ts_code=ts_code, token=token)
        if not bars:
            print(f"    无数据")
            continue

        lab.save_bar_data(bars)
        print(f"    {len(bars)} 条")

        if SLEEP_SECONDS > 0:
            time.sleep(SLEEP_SECONDS)


def main():
    # 支持命令行指定股票
    custom_codes = sys.argv[1:] if len(sys.argv) > 1 else None

    if custom_codes:
        stock_pool = custom_codes
        print(f"自定义股票池: {len(stock_pool)} 只")
    elif STOCK_POOL_MODE == "dynamic":
        stock_pool = get_dynamic_stock_pool()
        print(f"动态股票池: {len(stock_pool)} 只")
    else:
        stock_pool = STATIC_STOCK_POOL
        print(f"固定股票池: {len(stock_pool)} 只")

    token = os.getenv("TUSHARE_TOKEN", TUSHARE_TOKEN)

    print("\n" + "=" * 60)
    print("Step 1: 拉取信号数据")
    print("=" * 60)
    signal_df = fetch_signal_batched(stock_pool, token)

    if signal_df.is_empty():
        print("\n无信号数据，退出")
        return

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
