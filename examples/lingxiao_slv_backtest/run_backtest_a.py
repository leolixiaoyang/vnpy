"""
Lingxiao A股两层模型动量策略回测脚本。

目标品种：科创50ETF (588000.SHSE)
参考品种：沪深300ETF、创业板ETF、上证指数ETF

数据获取：
- 优先从 AlphaLab 加载已存储的历史数据
- 若 AlphaLab 无数据，自动通过 tushare 获取 ETF 日线数据
- tushare 获取的数据会自动写入 AlphaLab 供后续使用

运行方式：
    python run_backtest_a.py
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import polars as pl

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config_a import (  # noqa: E402
    CONTRACT_SETTINGS,
    END_DATE,
    INITIAL_CAPITAL,
    INTERVAL,
    LAB_PATH,
    MODEL_PARAMS,
    REFERENCE_SYMBOLS,
    SIGNAL_CACHE,
    START_DATE,
    STRATEGY_PARAMS,
    VT_SYMBOL,
)
from signal_pipeline_a import LingxiaoASignalPipeline, PipelineConfig  # noqa: E402
from vnpy.alpha import AlphaLab, BacktestingEngine  # noqa: E402
from vnpy.strategies.lingxiao_slv_strategy import LingxiaoSlvStrategy  # noqa: E402


def ensure_contract_settings(lab: AlphaLab, vt_symbols: list[str]) -> None:
    """补齐回测需要的合约配置。"""
    current_settings = lab.load_contract_setttings()

    for vt_symbol in vt_symbols:
        if vt_symbol in current_settings:
            continue

        lab.add_contract_setting(vt_symbol=vt_symbol, **CONTRACT_SETTINGS)


def generate_signal(lab: AlphaLab) -> pl.DataFrame:
    """生成并缓存信号。"""
    pipeline = LingxiaoASignalPipeline(
        lab=lab,
        config=PipelineConfig(
            target_symbol=VT_SYMBOL,
            reference_symbols=REFERENCE_SYMBOLS,
            start=START_DATE,
            end=END_DATE,
            interval=INTERVAL,
            **MODEL_PARAMS,
        ),
    )

    signal_df = pipeline.generate_signal().sort("datetime")
    SIGNAL_CACHE.parent.mkdir(parents=True, exist_ok=True)
    signal_df.write_parquet(SIGNAL_CACHE)
    return signal_df


def run_backtest() -> dict:
    """运行回测。"""
    lab = AlphaLab(str(LAB_PATH))

    all_symbols = [VT_SYMBOL, *REFERENCE_SYMBOLS.values()]
    ensure_contract_settings(lab, all_symbols)

    # 检查信号缓存是否存在
    if SIGNAL_CACHE.exists():
        print(f"加载已有信号缓存: {SIGNAL_CACHE}")
        signal_df = pl.read_parquet(SIGNAL_CACHE)
    else:
        print("生成新信号...")
        signal_df = generate_signal(lab)

    engine = BacktestingEngine(lab)
    engine.set_parameters(
        vt_symbols=[VT_SYMBOL],
        interval=INTERVAL,
        start=datetime.fromisoformat(START_DATE),
        end=datetime.fromisoformat(END_DATE),
        capital=INITIAL_CAPITAL,
    )
    engine.add_strategy(LingxiaoSlvStrategy, STRATEGY_PARAMS, signal_df)

    engine.load_data()
    engine.run_backtesting()
    result_df = engine.calculate_result()
    statistics = engine.calculate_statistics()

    print("\n信号样例:")
    print(signal_df.tail(10))

    if result_df is not None:
        print("\n逐日结果尾部:")
        print(result_df.tail(10))

    return statistics


if __name__ == "__main__":
    stats = run_backtest()
    print("\n回测统计:")
    for key, value in stats.items():
        print(f"{key}: {value}")