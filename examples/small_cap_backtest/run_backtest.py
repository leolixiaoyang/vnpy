"""小市值杠铃策略回测脚本。"""

from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path

import matplotlib
import polars as pl
import tinyshare as ts

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import (  # noqa: E402
    CONTRACT_SETTINGS,
    END_DATE,
    GOLD_VT_SYMBOL,
    INITIAL_CAPITAL,
    INTERVAL,
    LAB_PATH,
    SIGNAL_CACHE,
    START_DATE,
    STRATEGY_PARAMS,
    STOCK_POOL_MODE,
    TS_STOCK_POOL,
    TUSHARE_TOKEN,
    USE_SIGNAL_CACHE,
    VT_SYMBOLS,
    get_dynamic_stock_pool,
)
from signal_pipeline import SignalConfig, SmallCapSignalPipeline  # noqa: E402
from vnpy.alpha import AlphaLab, BacktestingEngine  # noqa: E402
from vnpy.trader.constant import Exchange  # noqa: E402
from vnpy.trader.object import BarData  # noqa: E402
from vnpy.strategies.small_cap_strategy import SmallCapBarbellStrategy  # noqa: E402


def ensure_contract_settings(lab: AlphaLab, vt_symbols: list[str]) -> None:
    """补齐回测需要的合约配置。"""
    current_settings = lab.load_contract_setttings()

    for vt_symbol in vt_symbols:
        if vt_symbol in current_settings:
            continue

        lab.add_contract_setting(vt_symbol=vt_symbol, **CONTRACT_SETTINGS)


def generate_signal() -> pl.DataFrame:
    """构建策略信号。"""
    token = os.getenv("TUSHARE_TOKEN", TUSHARE_TOKEN)
    
    # 根据模式选择股票池
    if STOCK_POOL_MODE == "dynamic":
        stock_pool = get_dynamic_stock_pool(token)
        print(f"使用动态股票池: {len(stock_pool)} 只")
    else:
        stock_pool = TS_STOCK_POOL
        print(f"使用固定股票池: {len(stock_pool)} 只")
    
    pipeline = SmallCapSignalPipeline(
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
    return signal_df


def _ts_to_vt_symbol(ts_code: str) -> str:
    return ts_code.replace(".SZ", ".SZSE").replace(".SH", ".SSE")


def _download_daily_bars(ts_code: str, token: str) -> list[BarData]:
    ts.set_token(token)
    pro = ts.pro_api()

    # 判断是否为基金/ETF：以51开头的上交所代码或15开头的深交所代码
    is_fund = ts_code.startswith("51") or ts_code.startswith("15")

    if is_fund:
        raw_df = pro.fund_daily(
            ts_code=ts_code,
            start_date=START_DATE.replace("-", ""),
            end_date=END_DATE.replace("-", ""),
        )
    else:
        raw_df = pro.daily(
            ts_code=ts_code,
            start_date=START_DATE.replace("-", ""),
            end_date=END_DATE.replace("-", ""),
        )
    if raw_df is None or len(raw_df) == 0:
        return []

    df = pl.DataFrame(raw_df).sort("trade_date")
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


def ensure_bar_data(lab: AlphaLab, vt_symbols: list[str]) -> None:
    """确保 AlphaLab 内存在回测所需行情数据。"""
    token = os.getenv("TUSHARE_TOKEN", TUSHARE_TOKEN)

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
        print(f"下载并写入行情: {ts_code}")
        bars = _download_daily_bars(ts_code=ts_code, token=token)
        if not bars:
            print(f"  跳过，无可用数据: {ts_code}")
            continue

        lab.save_bar_data(bars)
        print(f"  已写入 {len(bars)} 条")


def run_backtest() -> dict:
    """运行回测。"""
    lab = AlphaLab(str(LAB_PATH))

    # 先生成或加载信号
    if USE_SIGNAL_CACHE and SIGNAL_CACHE.exists():
        print(f"加载信号缓存: {SIGNAL_CACHE}")
        signal_df = pl.read_parquet(SIGNAL_CACHE)
    else:
        print("生成信号数据...")
        signal_df = generate_signal()

    # 从信号数据中提取 vt_symbols（动态股票池）
    if not signal_df.is_empty() and "vt_symbol" in signal_df.columns:
        stock_symbols = list(signal_df["vt_symbol"].unique())
    else:
        stock_symbols = VT_SYMBOLS  # 回退到固定池
    
    all_symbols = list(dict.fromkeys([*stock_symbols, GOLD_VT_SYMBOL]))
    print(f"回测标的: {len(all_symbols)} 只")
    
    ensure_contract_settings(lab, all_symbols)
    ensure_bar_data(lab, all_symbols)

    engine = BacktestingEngine(lab)
    engine.set_parameters(
        vt_symbols=all_symbols,
        interval=INTERVAL,
        start=datetime.fromisoformat(START_DATE),
        end=datetime.fromisoformat(END_DATE),
        capital=INITIAL_CAPITAL,
    )
    engine.add_strategy(SmallCapBarbellStrategy, STRATEGY_PARAMS, signal_df)

    engine.load_data()
    engine.run_backtesting()
    result_df = engine.calculate_result()
    statistics = engine.calculate_statistics()

    print("\n信号数据样例:")
    print(signal_df.tail(20))

    if result_df is not None:
        print("\n逐日结果尾部:")
        print(result_df.tail(20))

        result_path = LAB_PATH / "backtest_result_small_cap.csv"
        result_df.to_csv(result_path, index=True)
        print(f"\n回测结果已保存: {result_path}")

        if "balance" in result_df.columns:
            fig_path = LAB_PATH / "small_cap_equity_curve.png"
            fig, ax = plt.subplots(figsize=(11, 5))
            result_df["balance"].plot(ax=ax, color="#1f77b4", linewidth=1.5)
            ax.set_title("Small Cap Barbell Equity Curve")
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
