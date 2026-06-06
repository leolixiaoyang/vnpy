"""Run a 3-month backtest and print detailed operation logs."""
from __future__ import annotations

import json
from pathlib import Path

from config import INITIAL_CAPITAL, TUSHARE_TOKEN
from data_client import TinyshareClient
from strategy import AllWeatherRotationBacktester

START_DATE = "20240101"
END_DATE = "20240331"


def format_date(d: str) -> str:
    return f"{d[:4]}-{d[4:6]}-{d[6:]}"


def run() -> None:
    client = TinyshareClient(token=TUSHARE_TOKEN, use_cache=True)
    engine = AllWeatherRotationBacktester(
        client=client,
        start_date=START_DATE,
        end_date=END_DATE,
        initial_capital=INITIAL_CAPITAL,
    )

    trades_df, equity_df = engine.run()

    # ---- 输出汇总 ----
    print("=" * 80)
    print(f"回测区间: {format_date(START_DATE)} ~ {format_date(END_DATE)}")
    print(f"初始资金: {INITIAL_CAPITAL:,.0f}")
    print("=" * 80)

    # 每日净值曲线
    print("\n【每日净值曲线】")
    if not equity_df.empty:
        for _, row in equity_df.iterrows():
            equity = float(row.get("equity", 0))
            cash = float(row.get("cash", 0))
            mv = float(row.get("market_value", 0))
            pos_count = int(row.get("position_count", 0))
            print(f"  {format_date(str(row['trade_date']))} | 权益={equity:,.2f} | 现金={cash:,.2f} | 市值={mv:,.2f} | 持仓数={pos_count}")

    # 交易记录
    print(f"\n【交易记录】（共 {len(trades_df)} 笔）")
    if not trades_df.empty:
        for _, row in trades_df.iterrows():
            action = row.get("action", "")
            price = float(row.get("price", 0))
            volume = int(row.get("volume", 0))
            turnover = float(row.get("turnover", 0))
            fee = float(row.get("fee", 0))
            reason = row.get("reason", "")
            code = row.get("ts_code", "")
            trade_date = format_date(str(row["trade_date"]))
            action_cn = "买入" if action == "BUY" else "卖出"
            print(f"  {trade_date} | {action_cn} | {code} | 价格={price:.3f} | 数量={volume} | 金额={turnover:,.2f} | 费用={fee:.2f} | 原因={reason}")

    # 统计摘要
    if not equity_df.empty:
        eq = equity_df.copy()
        eq["equity"] = pd.to_numeric(eq["equity"], errors="coerce")
        eq = eq.dropna(subset=["equity"]).reset_index(drop=True)
        if not eq.empty:
            net_value = eq.iloc[-1]["equity"] / INITIAL_CAPITAL
            total_return = net_value - 1.0
            running_max = eq["equity"].cummax()
            drawdown = eq["equity"] / running_max - 1.0
            max_drawdown = float(drawdown.min())
            print(f"\n【回测统计】")
            print(f"  最终权益: {eq.iloc[-1]['equity']:,.2f}")
            print(f"  净值: {net_value:.4f}")
            print(f"  总收益率: {total_return:.2%}")
            print(f"  最大回撤: {max_drawdown:.2%}")
            print(f"  交易天数: {len(eq)}")
            if not trades_df.empty:
                print(f"  买入笔数: {len(trades_df[trades_df['action'] == 'BUY'])}")
                print(f"  卖出笔数: {len(trades_df[trades_df['action'] == 'SELL'])}")

    # 导出 JSON 供后续文档生成使用
    result: dict = {
        "start_date": format_date(START_DATE),
        "end_date": format_date(END_DATE),
        "initial_capital": INITIAL_CAPITAL,
    }

    if not equity_df.empty:
        eq = equity_df.copy()
        eq["equity"] = pd.to_numeric(eq["equity"], errors="coerce")
        eq = eq.dropna(subset=["equity"]).reset_index(drop=True)
        if not eq.empty:
            net_value = eq.iloc[-1]["equity"] / INITIAL_CAPITAL
            running_max = eq["equity"].cummax()
            drawdown = eq["equity"] / running_max - 1.0
            result["summary"] = {
                "final_equity": float(eq.iloc[-1]["equity"]),
                "net_value": float(net_value),
                "total_return": float(net_value - 1.0),
                "max_drawdown": float(drawdown.min()),
                "trading_days": len(eq),
            }

    if not trades_df.empty:
        trades_list = []
        for _, row in trades_df.iterrows():
            trades_list.append({
                "trade_date": format_date(str(row["trade_date"])),
                "action": "买入" if row.get("action") == "BUY" else "卖出",
                "ts_code": row.get("ts_code", ""),
                "price": float(row.get("price", 0)),
                "volume": int(row.get("volume", 0)),
                "turnover": float(row.get("turnover", 0)),
                "fee": float(row.get("fee", 0)),
                "reason": row.get("reason", ""),
            })
        result["trades"] = trades_list

    if not equity_df.empty:
        eq_list = []
        for _, row in equity_df.iterrows():
            eq_list.append({
                "trade_date": format_date(str(row["trade_date"])),
                "equity": float(row.get("equity", 0)),
                "cash": float(row.get("cash", 0)),
                "market_value": float(row.get("market_value", 0)),
                "position_count": int(row.get("position_count", 0)),
            })
        result["equity_curve"] = eq_list

    Path("3m_backtest_result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n详细数据已导出到 3m_backtest_result.json")


if __name__ == "__main__":
    import pandas as pd
    run()
