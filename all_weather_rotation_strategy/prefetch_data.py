"""预下载回测所需的全部数据到本地 parquet 缓存。

运行方式：
    python prefetch_data.py

区间和参数在下方配置，跑一次后回测全走缓存，不再调 API。
"""
from __future__ import annotations

import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd

# ==================== 配置区 ====================
START_DATE = "2024-01-01"
END_DATE = "2026-04-30"

BIG_INDEX = "000300.SH"
SMALL_INDEX = "399101.SZ"

ETF_LIST = ["518880.SH", "513030.SH", "513100.SH", "164824.SZ", "159866.SZ"]

# 防限频：每 N 只股票暂停
SLEEP_EVERY = 30
SLEEP_SECONDS = 1.0

# Tushare token（优先环境变量）
TUSHARE_TOKEN = "bNP3yb6kn4CCht3IGVh96GjeRvh72t78FWDwPFe0n2yF2X0w89KsSFjOc54c8a35"
# ================================================

# 确保 config 中的 token 生效
import os
if "TUSHARE_TOKEN" not in os.environ:
    os.environ["TUSHARE_TOKEN"] = TUSHARE_TOKEN

sys.path.insert(0, str(Path(__file__).resolve().parent))
from data_client import TinyshareClient


def get_all_codes(client: TinyshareClient) -> set[str]:
    """通过 index_weight 获取两个指数在区间内全部成分股"""
    codes: set[str] = set()
    for index_code, name in [(BIG_INDEX, "沪深300"), (SMALL_INDEX, "中证A股")]:
        result = client.index_constituents(index_code, START_DATE)
        if result:
            codes.update(result)
            print(f"  [{name}] 成分股: {len(result)} 只")
        else:
            print(f"  [{name}] 未获取到，使用兜底池")
            if index_code == BIG_INDEX:
                codes.update(["600519.SH", "600036.SH", "601318.SH"])
            else:
                codes.update(["000001.SZ", "000002.SZ", "000333.SZ"])
    return codes


def prefetch() -> None:
    print(f"=== 预下载数据 ===")
    print(f"区间: {START_DATE} ~ {END_DATE}")
    print(f"缓存目录: 见 data/tushare/all_weather_rotation/")
    print()

    client = TinyshareClient(token=TUSHARE_TOKEN, use_cache=True)

    # 1. 股票基本信息
    print("1. 股票基本信息 ...")
    client.stock_basic()
    print()

    # 2. 指数日线（用于构建交易日历）
    print("2. 指数日线 ...")
    for code, name in [(BIG_INDEX, "沪深300"), (SMALL_INDEX, "中证A股")]:
        client.daily(ts_code=code, start_date=START_DATE, end_date=END_DATE, adj=None)
        print(f"  [{name}] done")
    print()

    # 3. 指数成分股
    print("3. 指数成分股 ...")
    all_codes = get_all_codes(client)
    print(f"  去重后: {len(all_codes)} 只")
    print()

    # 4. 股票日线
    codes = sorted(all_codes)
    print(f"4. 股票日线 ({len(codes)} 只) ...")
    for i, code in enumerate(codes):
        try:
            client.daily(ts_code=code, start_date=START_DATE, end_date=END_DATE, adj=None)
        except Exception as e:
            print(f"  [{i+1}/{len(codes)}] {code} 失败: {e}")
        if (i + 1) % 10 == 0:
            print(f"  进度: {i+1}/{len(codes)}")
        if (i + 1) % SLEEP_EVERY == 0:
            time.sleep(SLEEP_SECONDS)
    print()

    # 5. ETF 日线
    print("5. ETF 日线 ...")
    for code in ETF_LIST:
        try:
            client.daily(ts_code=code, start_date=START_DATE, end_date=END_DATE, adj=None)
            print(f"  {code} done")
        except Exception as e:
            print(f"  {code} 失败: {e}")
        time.sleep(0.3)
    print()

    # 6. daily_basic（按月批量拉取）
    print("6. daily_basic ...")
    start_dt = datetime.strptime(START_DATE.replace("-", ""), "%Y%m%d")
    end_dt = datetime.strptime(END_DATE.replace("-", ""), "%Y%m%d")

    # 生成每月月初日期
    months = []
    cur = start_dt.replace(day=1)
    while cur <= end_dt:
        months.append(cur.strftime("%Y-%m-%d"))
        # 下月1日
        if cur.month == 12:
            cur = cur.replace(year=cur.year + 1, month=1, day=1)
        else:
            cur = cur.replace(month=cur.month + 1, day=1)

    # 每月拉取一次 daily_basic（每次100只一批）
    for i, month in enumerate(months):
        try:
            client.daily_basic(ts_codes=codes, trade_date=month)
            print(f"  [{i+1}/{len(months)}] {month} done")
        except Exception as e:
            print(f"  [{i+1}/{len(months)}] {month} 失败: {e}")
        if (i + 1) % SLEEP_EVERY == 0:
            time.sleep(SLEEP_SECONDS)
    print()

    # 7. 财务四表（逐只拉取）
    print(f"7. 财务四表 ({len(codes)} 只) ...")
    for i, code in enumerate(codes):
        try:
            client.latest_fina_indicator(code, END_DATE)
            client.latest_income(code, END_DATE)
            client.latest_balance(code, END_DATE)
            client.latest_cashflow(code, END_DATE)
        except Exception as e:
            print(f"  [{i+1}/{len(codes)}] {code} 失败: {e}")
        if (i + 1) % 10 == 0:
            print(f"  进度: {i+1}/{len(codes)}")
        if (i + 1) % SLEEP_EVERY == 0:
            time.sleep(SLEEP_SECONDS)
    print()

    # 统计
    cache_dir = client._cache_file("tmp").parent
    files = list(cache_dir.iterdir())
    total_size = sum(f.stat().st_size for f in files) / 1024 / 1024
    print(f"=== 预下载完成 ===")
    print(f"缓存文件数: {len(files)}")
    print(f"缓存大小: {total_size:.1f} MB")
    print(f"缓存路径: {cache_dir}")


if __name__ == "__main__":
    prefetch()
