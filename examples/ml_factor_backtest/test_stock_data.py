"""测试脚本 — 指定股票检查数据完整性。

用法：
    python test_stock_data.py                          # 测试前5只中证1000成分股
    python test_stock_data.py 000012.SZ               # 测试单只
    python test_stock_data.py 000012.SZ 600000.SH     # 测试多只
"""

from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import polars as pl

from examples.ml_factor_backtest.signal_pipeline import MlFactorSignalPipeline, SignalConfig
from examples.ml_factor_backtest.config import get_dynamic_stock_pool, START_DATE, END_DATE, TUSHARE_TOKEN

# 需要验证的所有因子列
ALL_FACTOR_COLS = [
    "sgai", "net_profit_margin_ttm", "retained_profit_per_share",
    "total_profit_to_cost_ratio", "inventory_turnover_rate",
    "debt_to_assets", "operating_cost_to_revenue_ratio",
    "sales_growth_5y", "cashflow_per_share_ttm",
    "non_operating_net_profit_ttm", "eps",
]

ALL_TECH_COLS = [
    "arbr", "vol120", "davol20", "tvstd6", "price_1y",
    "sharpe_ratio_120", "price_no_fq",
]

ALL_BASE_COLS = [
    "datetime", "vt_symbol", "market_cap", "close", "pre_close",
    "limit_up", "limit_down", "list_days", "is_paused", "is_st",
]

EXPECTED_COLS = ALL_BASE_COLS + ALL_TECH_COLS + ALL_FACTOR_COLS


def check_stock(ts_code: str, start: str = START_DATE, end: str = END_DATE) -> None:
    print(f"\n{'='*70}")
    print(f"测试: {ts_code}  区间: {start} ~ {end}")
    print(f"{'='*70}")

    config = SignalConfig(ts_codes=[ts_code], start_date=start, end_date=end, token=TUSHARE_TOKEN)
    pipeline = MlFactorSignalPipeline(config)

    try:
        df = pipeline.generate()
    except Exception as e:
        print(f"  错误: {e}")
        import traceback; traceback.print_exc()
        return

    if df.is_empty():
        print(f"  结果: EMPTY (0 rows)")
        return

    print(f"  形状: {df.shape}")

    # 缺失列
    missing = [c for c in EXPECTED_COLS if c not in df.columns]
    present = [c for c in EXPECTED_COLS if c in df.columns]
    print(f"  列: {len(present)}/{len(EXPECTED_COLS)} present")
    if missing:
        print(f"  缺失: {missing}")

    # 因子列空值统计
    total = df.height
    factor_cols = [c for c in ALL_FACTOR_COLS if c in df.columns]
    tech_cols = [c for c in ALL_TECH_COLS if c in df.columns]

    if factor_cols:
        print(f"\n  基本面因子:")
        for c in factor_cols:
            nn = df.filter(pl.col(c).is_not_null()).height
            pct = f"{nn/total:.0%}" if total > 0 else "0%"
            status = "OK" if nn > 0 else "ALL_NULL"
            print(f"    {c:40s} {nn:5d}/{total:5d} ({pct})  {status}")

    if tech_cols:
        print(f"\n  技术因子:")
        for c in tech_cols:
            nn = df.filter(pl.col(c).is_not_null()).height
            pct = f"{nn/total:.0%}" if total > 0 else "0%"
            status = "OK" if nn > 0 else "ALL_NULL"
            print(f"    {c:40s} {nn:5d}/{total:5d} ({pct})  {status}")

    # 输出 CSV 供查看
    csv_path = Path(__file__).resolve().parent / "test_output"
    csv_path.mkdir(exist_ok=True)
    out_file = csv_path / f"{ts_code.replace('.', '_')}_test.csv"
    df.write_csv(out_file)
    print(f"\n  数据已保存: {out_file}")


def main():
    # 如果命令行指定了股票代码，用指定的；否则用前5只成分股
    if len(sys.argv) > 1:
        codes = sys.argv[1:]
    else:
        codes = get_dynamic_stock_pool()[:5]

    print(f"共测试 {len(codes)} 只股票:")
    for c in codes:
        print(f"  {c}")

    for code in codes:
        check_stock(code)


if __name__ == "__main__":
    main()
