"""导出每日信号明细到 CSV，用于上传飞书表格。

运行方式：
    cd examples/multi_ma_backtest && python export_daily.py
"""

from __future__ import annotations

import re
import sys
from datetime import datetime
from pathlib import Path

import polars as pl

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import (
    CONTRACT_SETTINGS,
    DAILY_BAR_CACHE,
    END_DATE,
    INITIAL_CAPITAL,
    INTERVAL,
    LAB_PATH,
    START_DATE,
    STRATEGY_PARAMS,
)
from vnpy.alpha import AlphaLab, BacktestingEngine
from vnpy.strategies.multi_ma_strategy import MultiMaStrategy


def ensure_contract_settings(lab: AlphaLab, vt_symbols: list[str]) -> None:
    current_settings = lab.load_contract_setttings()
    for vt_symbol in vt_symbols:
        if vt_symbol in current_settings:
            continue
        lab.add_contract_setting(vt_symbol=vt_symbol, **CONTRACT_SETTINGS)


def run_export() -> None:
    if not DAILY_BAR_CACHE.exists():
        print(f"错误：未找到行情数据，请先运行 python fetch_data.py")
        sys.exit(1)

    print(f"加载行情数据: {DAILY_BAR_CACHE}")
    daily_df = pl.read_parquet(DAILY_BAR_CACHE)

    ts_codes = daily_df["ts_code"].unique().to_list()
    vt_symbols = [c.replace(".SZ", ".SZSE").replace(".SH", ".SSE") for c in ts_codes]

    lab = AlphaLab(str(LAB_PATH))
    ensure_contract_settings(lab, vt_symbols)

    engine = BacktestingEngine(lab)
    engine.set_parameters(
        vt_symbols=vt_symbols,
        interval=INTERVAL,
        start=datetime.fromisoformat(START_DATE),
        end=datetime.fromisoformat(END_DATE),
        capital=INITIAL_CAPITAL,
    )

    empty_signal = pl.DataFrame()
    engine.add_strategy(MultiMaStrategy, STRATEGY_PARAMS, empty_signal)

    engine.load_data()
    engine.run_backtesting()
    engine.calculate_result()
    engine.calculate_statistics()

    # ========== 1. 构建每日 OHLCV + balance 表 ==========
    result_df = engine.daily_df
    if result_df is None:
        print("错误：无回测结果")
        sys.exit(1)

    # 从行情数据中提取每日 OHLCV
    ohlcv = daily_df.select([
        pl.col("datetime").alias("date"),
        pl.col("open"),
        pl.col("close"),
        pl.col("low"),
        pl.col("high"),
    ]).with_columns(pl.col("date").dt.date())

    # 合并 balance
    balance_df = result_df.select(["date", "balance"])
    daily = ohlcv.join(balance_df, on="date", how="left")

    # ========== 2. 从 engine.logs 提取信号 + 成交信息 ==========
    # T+1 模式：
    #   信号日 T: [信号] 多头排列 买入 @ 2025-02-24
    #   成交日 T+1: [成交] 多头排列 买入 12800.0股 @ 开盘77.30 + 滑点0.10% → 77.38
    #   或卖出:     [成交] 死叉 清仓 @ 开盘80.00 - 滑点0.10%

    all_dates = sorted(result_df["date"].to_list())

    def next_trading_date(date_str: str) -> str | None:
        dt = datetime.strptime(date_str, "%Y-%m-%d").date()
        for d in all_dates:
            if d > dt:
                return d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else str(d)
        return None

    # 2a. 解析信号日志
    signal_map: dict[str, dict] = {}
    for log_msg in engine.logs:
        m = re.search(r"\[信号\]\s*(.+?)\s*(买入|清仓)\s*@\s*(\d{4}-\d{2}-\d{2})", log_msg)
        if m:
            signal_map[m.group(3)] = {
                "action": "开仓" if m.group(2) == "买入" else "清仓",
                "reason": m.group(1),
            }

    # 2b. 解析成交日志，匹配信号日 → 成交日
    # 买入格式: [成交] 多头排列 买入 12800.0股 @ 开盘77.30 + 滑点0.10% → 77.38
    # 卖出格式: [成交] 死叉 清仓 @ 开盘80.00 - 滑点0.10%
    exec_info: dict[str, dict] = {}  # exec_date -> {action, reason, price, volume}

    def merge_exec(reason: str, action: str, exec_price: float, volume: int) -> None:
        # 找到匹配的未使用信号日
        signal_date = None
        for sd, sig in list(signal_map.items()):
            if sig["reason"] == reason and sig["action"] == action:
                signal_date = sd
                break
        if not signal_date:
            return
        del signal_map[signal_date]

        exec_date = next_trading_date(signal_date)
        if exec_date:
            exec_info[exec_date] = {
                "action": action,
                "reason": reason,
                "price": exec_price,
                "volume": volume,
            }

    for log_msg in engine.logs:
        # 买入: 提取 → 后的最终价格
        m_buy = re.search(
            r"\[成交\]\s*(.+?)\s*买入\s+([\d.]+)股\s*@\s*开盘[\d.]+\s*.*?→\s*([\d.]+)",
            log_msg
        )
        if m_buy:
            merge_exec(m_buy.group(1), "开仓", float(m_buy.group(3)), int(float(m_buy.group(2))))
            continue
        # 卖出: 计算 开盘 × (1 - 滑点)
        m_sell = re.search(r"\[成交\]\s*(.+?)\s*清仓\s*@\s*开盘([\d.]+)\s*-\s*滑点([\d.]+)%", log_msg)
        if m_sell:
            open_p = float(m_sell.group(2))
            slippage_pct = float(m_sell.group(3)) / 100
            exec_price = open_p * (1 - slippage_pct)
            merge_exec(m_sell.group(1), "清仓", exec_price, 0)

    # ========== 3. 合并成交信息到每日表 ==========
    daily = daily.with_columns([
        pl.lit("").alias("操作"),
        pl.lit("").alias("操作依据"),
        pl.lit(0.0).alias("成交价格"),
        pl.lit(0).alias("成交数量"),
    ])

    for date_str, ei in exec_info.items():
        mask = pl.col("date") == datetime.strptime(date_str, "%Y-%m-%d").date()
        daily = daily.with_columns([
            pl.when(mask).then(pl.lit(ei["action"])).otherwise(pl.col("操作")).alias("操作"),
            pl.when(mask).then(pl.lit(ei["reason"])).otherwise(pl.col("操作依据")).alias("操作依据"),
            pl.when(mask).then(pl.lit(ei["price"])).otherwise(pl.col("成交价格")).alias("成交价格"),
            pl.when(mask).then(pl.lit(ei["volume"])).otherwise(pl.col("成交数量")).alias("成交数量"),
        ])

    # 排序并选择最终列
    daily = daily.sort("date").select([
        "date", "open", "close", "low", "high",
        "操作", "操作依据", "成交价格", "成交数量", "balance",
    ])

    output_path = LAB_PATH / "daily_signals_latest.csv"
    daily.write_csv(output_path)
    print(f"每日信号明细已保存: {output_path}")
    print(f"共 {len(daily)} 行，其中有操作的 {daily.filter(pl.col('操作') != '').height} 行")


if __name__ == "__main__":
    run_export()
