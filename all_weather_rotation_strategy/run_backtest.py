from __future__ import annotations

from pathlib import Path

import pandas as pd

from config import END_DATE, INITIAL_CAPITAL, RESULT_PATH, START_DATE, TUSHARE_TOKEN
from data_client import TinyshareClient
from strategy import AllWeatherRotationBacktester


def _calc_summary(equity_df: pd.DataFrame, initial_capital: float) -> dict[str, float]:
    if equity_df.empty:
        return {}

    eq = equity_df.copy()
    eq["equity"] = pd.to_numeric(eq["equity"], errors="coerce")
    eq = eq.dropna(subset=["equity"]).reset_index(drop=True)
    if eq.empty:
        return {}

    eq["ret"] = eq["equity"].pct_change().fillna(0.0)
    net_value = eq.iloc[-1]["equity"] / initial_capital
    total_return = net_value - 1.0

    running_max = eq["equity"].cummax()
    drawdown = eq["equity"] / running_max - 1.0
    max_drawdown = float(drawdown.min())

    ann_factor = 252 / max(len(eq), 1)
    annual_return = float((net_value ** ann_factor) - 1.0)
    sharpe = float((eq["ret"].mean() / (eq["ret"].std() + 1e-12)) * (252 ** 0.5))

    return {
        "initial_capital": float(initial_capital),
        "final_equity": float(eq.iloc[-1]["equity"]),
        "net_value": float(net_value),
        "total_return": float(total_return),
        "annual_return": annual_return,
        "max_drawdown": max_drawdown,
        "sharpe": sharpe,
        "trading_days": float(len(eq)),
    }


def run() -> None:
    if not TUSHARE_TOKEN:
        raise ValueError("请先设置环境变量 TUSHARE_TOKEN")

    RESULT_PATH.mkdir(parents=True, exist_ok=True)

    client = TinyshareClient(token=TUSHARE_TOKEN, use_cache=True)
    engine = AllWeatherRotationBacktester(
        client=client,
        start_date=START_DATE,
        end_date=END_DATE,
        initial_capital=INITIAL_CAPITAL,
    )

    trades_df, equity_df = engine.run()

    trades_file = RESULT_PATH / "all_weather_trades.csv"
    equity_file = RESULT_PATH / "all_weather_equity.csv"
    summary_file = RESULT_PATH / "all_weather_summary.csv"

    if not trades_df.empty:
        trades_df.to_csv(trades_file, index=False, encoding="utf-8-sig")
    if not equity_df.empty:
        equity_df.to_csv(equity_file, index=False, encoding="utf-8-sig")

    summary = _calc_summary(equity_df, INITIAL_CAPITAL)
    if summary:
        pd.DataFrame([summary]).to_csv(summary_file, index=False, encoding="utf-8-sig")

    print("回测完成")
    print(f"交易记录: {trades_file}")
    print(f"净值曲线: {equity_file}")
    print(f"统计摘要: {summary_file}")
    if summary:
        for k, v in summary.items():
            print(f"{k}: {v}")


if __name__ == "__main__":
    run()
