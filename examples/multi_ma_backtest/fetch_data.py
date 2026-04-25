"""通过 tinyshare 获取日线行情数据，保存为 AlphaLab 兼容的 parquet 文件供回测使用。

运行方式：
    cd examples/multi_ma_backtest && python fetch_data.py
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import polars as pl
import tinyshare as ts

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import DAILY_BAR_CACHE, END_DATE, LAB_PATH, START_DATE, TS_CODE, TUSHARE_TOKEN


def fetch_daily() -> None:
    """获取日线数据并保存为 AlphaLab 兼容格式。"""
    ts.set_token(TUSHARE_TOKEN)
    pro = ts.pro_api()

    start = START_DATE.replace("-", "")
    end = END_DATE.replace("-", "")

    # AlphaLab 需要的路径: lab_data/multi_ma/daily/
    daily_dir = LAB_PATH / "daily"
    daily_dir.mkdir(parents=True, exist_ok=True)

    print(f"正在获取 {TS_CODE} 日线数据 ({START_DATE} ~ {END_DATE}) ...")

    df = pro.daily(
        ts_code=TS_CODE,
        start_date=start,
        end_date=end,
        adj="hfq",  # 后复权
    )

    if df is None or len(df) == 0:
        print("错误：未获取到数据")
        sys.exit(1)

    print(f"获取到 {len(df)} 条日线数据")

    data = pl.DataFrame(df)
    data = data.sort("trade_date")

    # 转换日期格式
    data = data.with_columns(
        pl.col("trade_date").cast(pl.Utf8).str.to_datetime("%Y%m%d").alias("datetime")
    )

    # 标准化列名（AlphaLab 需要的列）
    data = data.rename({"vol": "volume"})

    # 确保 AlphaLab 需要的列都存在
    required_cols = ["datetime", "open", "high", "low", "close", "volume"]
    for col in required_cols:
        if col not in data.columns:
            print(f"错误：缺少必要列 {col}")
            sys.exit(1)

    # 添加缺少的列（turnover, open_interest）
    if "turnover" not in data.columns:
        data = data.with_columns((pl.col("close") * pl.col("volume")).alias("turnover"))
    if "open_interest" not in data.columns:
        data = data.with_columns(pl.lit(0.0).alias("open_interest"))

    # 保存到 daily 目录（AlphaLab 格式）
    vt_symbol = TS_CODE.replace(".SH", ".SSE").replace(".SZ", ".SZSE")
    output_path = daily_dir / f"{vt_symbol}.parquet"

    select_cols = ["datetime", "open", "high", "low", "close", "volume", "turnover", "open_interest"]
    data.select(select_cols).write_parquet(output_path)

    print(f"日线数据已保存: {output_path}")

    # 同时保存一份完整的到缓存路径，供其他用途
    LAB_PATH.mkdir(parents=True, exist_ok=True)
    data.write_parquet(DAILY_BAR_CACHE)
    print(f"完整数据已保存: {DAILY_BAR_CACHE}")


if __name__ == "__main__":
    fetch_daily()
