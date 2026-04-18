"""ML 因子小市值策略回测脚本。

注意：运行前需先执行 `python fetch_data.py` 获取信号和行情数据。
"""

from __future__ import annotations

import os
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

from config import (  # noqa: E402
    CONTRACT_SETTINGS,
    END_DATE,
    INITIAL_CAPITAL,
    INTERVAL,
    LAB_PATH,
    SIGNAL_CACHE,
    START_DATE,
    STRATEGY_PARAMS,
)
from vnpy.alpha import AlphaLab, BacktestingEngine  # noqa: E402
from vnpy.strategies.ml_factor_strategy import MlFactorStrategy  # noqa: E402


def ensure_contract_settings(lab: AlphaLab, vt_symbols: list[str]) -> None:
    """补齐回测需要的合约配置。"""
    current_settings = lab.load_contract_setttings()

    for vt_symbol in vt_symbols:
        if vt_symbol in current_settings:
            continue
        lab.add_contract_setting(vt_symbol=vt_symbol, **CONTRACT_SETTINGS)


def run_backtest() -> dict:
    """运行回测。"""
    if not SIGNAL_CACHE.exists():
        print(f"错误：未找到信号数据，请先运行 python fetch_data.py")
        print(f"  预期路径: {SIGNAL_CACHE}")
        sys.exit(1)

    print(f"加载信号数据: {SIGNAL_CACHE}")
    signal_df = pl.read_parquet(SIGNAL_CACHE)

    vt_symbols = list(signal_df["vt_symbol"].unique())
    print(f"回测标的: {len(vt_symbols)} 只")

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
    engine.add_strategy(MlFactorStrategy, STRATEGY_PARAMS, signal_df)

    engine.load_data()
    engine.run_backtesting()
    result_df = engine.calculate_result()
    statistics = engine.calculate_statistics()

    if result_df is not None:
        result_path = LAB_PATH / "backtest_result_ml_factor.csv"
        result_df.write_csv(result_path)
        print(f"\n回测结果已保存: {result_path}")

        if "balance" in result_df.columns:
            fig_path = LAB_PATH / "ml_factor_equity_curve.png"
            fig, ax = plt.subplots(figsize=(11, 5))
            result_df["balance"].plot(ax=ax, color="#1f77b4", linewidth=1.5)
            ax.set_title("ML Factor Small Cap Equity Curve")
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
