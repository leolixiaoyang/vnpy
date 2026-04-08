"""导入 CSV 格式的 ETF 数据到 AlphaLab。

使用方法：
1. 从东方财富/同花顺等平台下载 ETF 日线数据 CSV 文件
2. CSV 文件应包含以下列：日期、开盘、收盘、最高、最低、成交量
3. 将 CSV 文件放到本脚本同目录下，命名为 <代码>.csv，如 588000.csv
4. 运行本脚本导入数据
"""

from __future__ import annotations

import csv
import sys
from datetime import datetime
from pathlib import Path

import polars as pl

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config_a import END_DATE, INTERVAL, LAB_PATH, REFERENCE_SYMBOLS, START_DATE, VT_SYMBOL
from vnpy.alpha import AlphaLab
from vnpy.trader.constant import Exchange
from vnpy.trader.object import BarData


# 列名映射（支持多种常见格式）
COLUMN_MAPS = {
    # 东方财富格式
    "东方财富": {
        "日期": "datetime",
        "开盘": "open",
        "收盘": "close",
        "最高": "high",
        "最低": "low",
        "成交量": "volume",
    },
    # 通达信格式
    "通达信": {
        "date": "datetime",
        "open": "open",
        "close": "close",
        "high": "high",
        "low": "low",
        "volume": "volume",
    },
    # 标准英文格式
    "standard": {
        "Date": "datetime",
        "Open": "open",
        "Close": "close",
        "High": "high",
        "Low": "low",
        "Volume": "volume",
    },
}


def parse_csv(csv_path: Path) -> pl.DataFrame | None:
    """解析 CSV 文件，自动识别列名格式。"""
    if not csv_path.exists():
        print(f"文件不存在: {csv_path}")
        return None
    
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    
    if not rows:
        print(f"CSV 文件为空: {csv_path}")
        return None
    
    # 尗试匹配列名格式
    raw_columns = list(rows[0].keys())
    column_map = None
    
    for format_name, map_dict in COLUMN_MAPS.items():
        if all(k in raw_columns for k in map_dict.keys()):
            column_map = map_dict
            print(f"识别为 {format_name} 格式")
            break
    
    if column_map is None:
        print(f"无法识别列名格式，原始列: {raw_columns}")
        print("请确保 CSV 包含：日期/开盘/收盘/最高/最低/成交量")
        return None
    
    # 解析数据
    parsed_rows = []
    for row in rows:
        try:
            # 解析日期
            date_str = row.get(list(column_map.keys())[0])
            if "/" in date_str:
                dt = datetime.strptime(date_str, "%Y/%m/%d")
            elif "-" in date_str:
                dt = datetime.strptime(date_str, "%Y-%m-%d")
            else:
                dt = datetime.strptime(date_str, "%Y%m%d")
            
            parsed_rows.append({
                "datetime": dt,
                "open": float(row[column_map["开盘"]]),
                "close": float(row[column_map["收盘"]]),
                "high": float(row[column_map["最高"]]),
                "low": float(row[column_map["最低"]]),
                "volume": float(row[column_map["成交量"]]),
            })
        except (ValueError, KeyError) as e:
            print(f"解析行失败: {row}, 错误: {e}")
            continue
    
    if not parsed_rows:
        return None
    
    df = pl.DataFrame(parsed_rows).sort("datetime")
    
    # 过滤日期范围
    start_dt = datetime.fromisoformat(START_DATE)
    end_dt = datetime.fromisoformat(END_DATE)
    df = df.filter(
        (pl.col("datetime") >= start_dt) &
        (pl.col("datetime") <= end_dt)
    )
    
    return df


def import_csv_to_lab(csv_path: Path, vt_symbol: str, lab: AlphaLab) -> bool:
    """将 CSV 数据导入 AlphaLab。"""
    df = parse_csv(csv_path)
    if df is None:
        return False
    
    symbol, exchange_str = vt_symbol.split(".")
    exchange = Exchange[exchange_str]
    
    bars = []
    for row in df.to_dicts():
        bar = BarData(
            symbol=symbol,
            exchange=exchange,
            datetime=row["datetime"],
            interval=INTERVAL,
            open_price=row["open"],
            high_price=row["high"],
            low_price=row["low"],
            close_price=row["close"],
            volume=row["volume"],
            gateway_name="CSV",
        )
        bars.append(bar)
    
    lab.save_bar_data(bars)
    print(f"成功导入 {len(bars)} 条数据到 {vt_symbol}")
    return True


def generate_sample_data(vt_symbol: str, lab: AlphaLab) -> None:
    """生成示例数据（仅用于测试回测脚本，非真实行情）。"""
    import numpy as np
    
    print(f"生成示例数据: {vt_symbol}")
    
    symbol, exchange_str = vt_symbol.split(".")
    exchange = Exchange[exchange_str]
    
    start_dt = datetime.fromisoformat(START_DATE)
    end_dt = datetime.fromisoformat(END_DATE)
    
    # 生成模拟日线
    np.random.seed(42)
    base_price = 1.0 if "588" in symbol else 4.0  # 不同 ETF 不同基准价
    days = (end_dt - start_dt).days
    
    prices = [base_price]
    for _ in range(days):
        change = np.random.randn() * 0.02  # 2% 日波动
        prices.append(prices[-1] * (1 + change))
    
    bars = []
    current_dt = start_dt
    price_idx = 0
    
    while current_dt <= end_dt:
        if current_dt.weekday() < 5:  # 工作日
            close = prices[min(price_idx, len(prices) - 1)]
            open_p = close * (1 + np.random.randn() * 0.005)
            high = max(open_p, close) * (1 + abs(np.random.randn() * 0.01))
            low = min(open_p, close) * (1 - abs(np.random.randn() * 0.01))
            volume = int(1e6 * (1 + np.random.randn() * 0.3))
            
            bar = BarData(
                symbol=symbol,
                exchange=exchange,
                datetime=current_dt,
                interval=INTERVAL,
                open_price=open_p,
                high_price=high,
                low_price=low,
                close_price=close,
                volume=volume,
                gateway_name="SAMPLE",
            )
            bars.append(bar)
            price_idx += 1
        
        current_dt = current_dt.replace(hour=0, minute=0, second=0)
        from datetime import timedelta
        current_dt += timedelta(days=1)
    
    lab.save_bar_data(bars)
    print(f"生成 {len(bars)} 条示例数据")


def main():
    """主函数。"""
    import argparse
    
    parser = argparse.ArgumentParser(description="ETF 数据导入工具")
    parser.add_argument("--sample", action="store_true", help="使用模拟数据测试")
    parser.add_argument("--force", action="store_true", help="强制重新导入")
    args = parser.parse_args()
    
    lab = AlphaLab(str(LAB_PATH))
    
    all_symbols = {"target": VT_SYMBOL}
    all_symbols.update(REFERENCE_SYMBOLS)
    
    script_dir = Path(__file__).resolve().parent
    
    print("=" * 60)
    print("ETF 数据导入工具")
    if args.sample:
        print("模式: 使用模拟数据")
    print("=" * 60)
    
    success_count = 0
    
    for alias, vt_symbol in all_symbols.items():
        print(f"\n处理 {alias}: {vt_symbol}")
        
        # 检查是否已有数据
        bars = lab.load_bar_data(vt_symbol, INTERVAL, START_DATE, END_DATE)
        if bars and not args.force:
            print(f"已有 {len(bars)} 条数据，跳过")
            success_count += 1
            continue
        
        symbol = vt_symbol.split(".")[0]
        csv_path = script_dir / f"{symbol}.csv"
        
        if csv_path.exists() and not args.sample:
            if import_csv_to_lab(csv_path, vt_symbol, lab):
                success_count += 1
        elif args.sample:
            generate_sample_data(vt_symbol, lab)
            success_count += 1
        else:
            print(f"未找到 CSV 文件: {csv_path}")
            print("请手动下载 ETF 日线数据并放到上述路径")
            print("或运行: python import_csv_data.py --sample 使用模拟数据测试")
    
    print("\n" + "=" * 60)
    print(f"完成: {success_count}/{len(all_symbols)} 个品种数据就绪")
    
    if success_count == len(all_symbols):
        print("可以运行回测: python run_backtest_a.py")


if __name__ == "__main__":
    main()