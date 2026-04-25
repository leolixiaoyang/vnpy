"""多均线择时策略回测脚本。

运行前需先执行 `python fetch_data.py` 获取行情数据。

运行方式：
    cd examples/multi_ma_backtest && python run_backtest.py
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import matplotlib
import polars as pl

matplotlib.use("Agg")
import matplotlib.pyplot as plt

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
    """补齐回测需要的合约配置。"""
    current_settings = lab.load_contract_setttings()

    for vt_symbol in vt_symbols:
        if vt_symbol in current_settings:
            continue
        lab.add_contract_setting(vt_symbol=vt_symbol, **CONTRACT_SETTINGS)


def run_backtest() -> dict:
    """运行回测。"""
    if not DAILY_BAR_CACHE.exists():
        print(f"错误：未找到行情数据，请先运行 python fetch_data.py")
        print(f"  预期路径: {DAILY_BAR_CACHE}")
        sys.exit(1)

    print(f"加载行情数据: {DAILY_BAR_CACHE}")
    daily_df = pl.read_parquet(DAILY_BAR_CACHE)

    # 获取 vt_symbol
    # tinyshare 返回的 ts_code 如 "600196.SH"，需要转换为 "600196.SSE"
    ts_codes = daily_df["ts_code"].unique().to_list()
    vt_symbols = [c.replace(".SZ", ".SZSE").replace(".SH", ".SSE") for c in ts_codes]

    print(f"回测标的: {vt_symbols}")

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

    # 多均线策略不需要 signal_df，传空 DataFrame
    empty_signal = pl.DataFrame()
    engine.add_strategy(MultiMaStrategy, STRATEGY_PARAMS, empty_signal)

    engine.load_data()
    engine.run_backtesting()
    engine.calculate_result()
    statistics = engine.calculate_statistics()

    # calculate_statistics 添加了 balance 列到 daily_df
    result_df = engine.daily_df

    if result_df is not None:
        result_path = LAB_PATH / "backtest_result_multi_ma.csv"
        result_df.write_csv(result_path)
        print(f"\n回测结果已保存: {result_path}")

        if "balance" in result_df.columns:
            fig_path = LAB_PATH / "multi_ma_equity_curve.png"
            fig, ax = plt.subplots(figsize=(11, 5))
            dates = result_df["date"].to_list()
            balances = result_df["balance"].to_list()
            ax.plot(dates, balances, color="#1f77b4", linewidth=1.5)
            ax.set_title("Multi MA Strategy Equity Curve")
            ax.set_xlabel("Date")
            ax.set_ylabel("Balance")
            ax.grid(True, linestyle="--", alpha=0.4)
            fig.tight_layout()
            fig.savefig(fig_path, dpi=160)
            plt.close(fig)
            print(f"净值曲线已保存: {fig_path}")

    return statistics


if __name__ == "__main__":
    stats = run_backtest()
    print("\n回测统计:")
    for key, value in stats.items():
        print(f"{key}: {value}")
