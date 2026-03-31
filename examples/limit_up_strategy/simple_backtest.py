"""
简单回测脚本
============
下载少量股票数据，运行一个简单的回测测试

作者：Shawn
日期：2026-03-31
"""

import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

# 添加策略路径
sys.path.insert(0, str(Path(__file__).parent))

import polars as pl
import tushare as ts

# 设置 Tushare
TUSHARE_TOKEN = os.getenv("TUSHARE_TOKEN", "a96ef9108067fe2b72a787c7d0e6a6974e6f05fd43fa3050497acdb4")
ts.set_token(TUSHARE_TOKEN)
pro = ts.pro_api()


def download_test_data():
    """下载测试数据（少量股票）"""
    print("=" * 50)
    print("步骤 1: 下载测试数据")
    print("=" * 50)
    
    # 选择 10 只活跃股票
    test_symbols = [
        "000001.SZ",  # 平安银行
        "000002.SZ",  # 万科 A
        "000063.SZ",  # 中兴通讯
        "000333.SZ",  # 美的集团
        "000651.SZ",  # 格力电器
        "000858.SZ",  # 五粮液
        "002304.SZ",  # 洋河股份
        "002594.SZ",  # 比亚迪
        "600000.SH",  # 浦发银行
        "600036.SH",  # 招商银行
        "600519.SH",  # 贵州茅台
        "601318.SH",  # 中国平安
    ]
    
    # 下载最近 1 年数据（获取更多涨停样本）
    end_date = datetime.now().strftime("%Y%m%d")
    start_date = (datetime.now() - timedelta(days=365)).strftime("%Y%m%d")
    
    print(f"下载区间：{start_date} 至 {end_date}")
    print(f"股票数量：{len(test_symbols)}")
    
    all_data = []
    
    for ts_code in test_symbols:
        try:
            df = pro.daily(ts_code=ts_code, start_date=start_date, end_date=end_date)
            if df is not None and len(df) > 0:
                df = pl.DataFrame(df)
                df = df.with_columns(pl.lit(ts_code).alias("ts_code"))
                all_data.append(df)
                print(f"  ✓ {ts_code}: {len(df)} 条记录")
        except Exception as e:
            print(f"  ✗ {ts_code}: {e}")
    
    if not all_data:
        print("错误：没有下载到任何数据")
        return None
    
    # 合并数据
    result = pl.concat(all_data)
    print(f"\n总计：{len(result)} 条记录")
    
    # 保存数据
    data_path = Path(__file__).parent.parent.parent / "data" / "tushare"
    data_path.mkdir(parents=True, exist_ok=True)
    
    save_file = data_path / "test_data.parquet"
    result.write_parquet(save_file)
    print(f"数据已保存：{save_file}")
    
    return result


def prepare_bar_data(daily_df: pl.DataFrame) -> list:
    """
    将日线数据转换为 vnpy 的 BarData 格式
    
    由于 vnpy 的 CTA 回测引擎主要支持分钟线，
    这里我们创建一个简化的日线回测测试
    """
    print("\n" + "=" * 50)
    print("步骤 2: 准备回测数据")
    print("=" * 50)
    
    # 转换格式
    bars_df = daily_df.rename({
        "trade_date": "datetime",
        "ts_code": "vt_symbol"
    })
    
    bars_df = bars_df.with_columns([
        pl.col("datetime").str.to_datetime("%Y%m%d"),
        pl.col("vt_symbol").str.to_uppercase(),
    ])
    
    print(f"数据条数：{len(bars_df)}")
    print(f"股票数量：{len(bars_df['vt_symbol'].unique())}")
    print(f"日期范围：{bars_df['datetime'].min()} 至 {bars_df['datetime'].max()}")
    
    return bars_df


def identify_limit_up_stocks(df: pl.DataFrame) -> pl.DataFrame:
    """识别涨停股票"""
    print("\n" + "=" * 50)
    print("步骤 3: 识别涨停股票")
    print("=" * 50)
    
    # 根据股票代码判断涨停幅度
    def get_limit_rate(ts_code: str) -> float:
        ts_code_upper = ts_code.upper()
        if ts_code_upper.startswith("688"):  # 科创板
            return 0.20
        elif ts_code_upper.startswith("300"):  # 创业板
            return 0.20
        elif ts_code_upper.startswith("8") or ts_code_upper.startswith("4"):  # 北交所
            return 0.30
        else:  # 主板
            return 0.10
    
    # 计算涨停价
    df = df.with_columns([
        pl.col("vt_symbol").map_elements(get_limit_rate, return_dtype=pl.Float64).alias("limit_rate"),
        (pl.col("pre_close") * (1 + pl.col("vt_symbol").map_elements(get_limit_rate, return_dtype=pl.Float64) - 0.005)).alias("limit_price")
    ])
    
    # 判断涨停
    df = df.with_columns([
        ((pl.col("close") >= pl.col("limit_price")) & 
         (pl.col("close") == pl.col("high"))).alias("is_limit_up")
    ])
    
    # 统计涨停股票
    limit_up_count = df.filter(pl.col("is_limit_up") == True).height
    print(f"涨停股票数量：{limit_up_count}")
    
    if limit_up_count > 0:
        print("\n涨停股票示例:")
        print(
            df.filter(pl.col("is_limit_up") == True)
            .select(["datetime", "vt_symbol", "close", "pct_chg"])
            .head(10)
        )
    
    return df


def simple_backtest(df: pl.DataFrame):
    """
    简化版回测
    模拟：昨日涨停，今日买入，次日卖出的策略
    """
    print("\n" + "=" * 50)
    print("步骤 4: 运行简化回测")
    print("=" * 50)
    
    # 筛选涨停股票
    limit_up_df = df.filter(pl.col("is_limit_up") == True)
    
    if limit_up_df.is_empty():
        print("测试期间没有涨停股票，无法回测")
        print("这可能是因为：")
        print("  1. 数据时间范围太短")
        print("  2. 所选股票近期无涨停")
        print("  3. 涨停判定条件过于严格")
        return None
    
    # 按日期分组
    dates = sorted(limit_up_df["datetime"].unique())
    
    print(f"\n有涨停的交易日：{len(dates)} 天")
    
    # 模拟交易
    initial_capital = 1000000  # 100 万
    capital = initial_capital
    trades = []
    
    for i, date in enumerate(dates[:-1]):  # 最后一天不买入
        # 获取当日涨停股票
        day_limit_up = limit_up_df.filter(pl.col("datetime") == date)
        
        # 按市值排序（这里简化为按收盘价排序）
        day_limit_up = day_limit_up.sort("close", descending=True)
        
        # 选前 3 只（简化测试）
        buy_stocks = day_limit_up.head(3)
        
        if buy_stocks.is_empty():
            continue
        
        # 获取次日数据
        next_date = dates[i + 1]
        next_day_df = df.filter(pl.col("datetime") == next_date)
        
        # 计算收益
        for stock in buy_stocks.iter_rows(named=True):
            vt_symbol = stock["vt_symbol"]
            buy_price = stock["close"]
            
            # 查找次日收盘价
            next_stock = next_day_df.filter(pl.col("vt_symbol") == vt_symbol)
            
            if next_stock.is_empty():
                continue
            
            sell_price = next_stock["close"][0]
            
            # 计算收益率
            return_rate = (sell_price - buy_price) / buy_price
            
            # 记录交易
            trades.append({
                "buy_date": date,
                "sell_date": next_date,
                "vt_symbol": vt_symbol,
                "buy_price": buy_price,
                "sell_price": sell_price,
                "return_rate": return_rate
            })
            
            # 更新资金（简化，不考虑仓位管理）
            position_value = capital / 3  # 等分 3 份
            capital += position_value * return_rate
    
    # 统计结果
    if not trades:
        print("没有产生任何交易")
        return None
    
    print(f"\n交易次数：{len(trades)}")
    
    # 计算统计指标
    total_return = (capital - initial_capital) / initial_capital * 100
    
    returns = [t["return_rate"] for t in trades]
    win_trades = [r for r in returns if r > 0]
    loss_trades = [r for r in returns if r <= 0]
    
    win_rate = len(win_trades) / len(trades) * 100 if trades else 0
    avg_win = sum(win_trades) / len(win_trades) * 100 if win_trades else 0
    avg_loss = sum(loss_trades) / len(loss_trades) * 100 if loss_trades else 0
    
    # 输出结果
    print("\n" + "=" * 50)
    print("回测结果")
    print("=" * 50)
    print(f"初始资金：¥{initial_capital:,.2f}")
    print(f"最终资金：¥{capital:,.2f}")
    print(f"总收益率：{total_return:.2f}%")
    print(f"交易次数：{len(trades)}")
    print(f"胜率：{win_rate:.2f}%")
    print(f"平均盈利：{avg_win:.2f}%")
    print(f"平均亏损：{avg_loss:.2f}%")
    
    # 显示部分交易记录
    print("\n交易记录示例（前 10 条）:")
    trade_df = pl.DataFrame(trades)
    print(trade_df.head(10))
    
    return {
        "initial_capital": initial_capital,
        "final_capital": capital,
        "total_return": total_return,
        "trade_count": len(trades),
        "win_rate": win_rate,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "trades": trades
    }


def main():
    """主函数"""
    print("\n" + "=" * 50)
    print("昨日涨停今日买入策略 - 简单回测")
    print("=" * 50)
    
    # 1. 下载测试数据
    daily_df = download_test_data()
    if daily_df is None:
        return
    
    # 2. 准备数据
    bars_df = prepare_bar_data(daily_df)
    
    # 3. 识别涨停
    df_with_limit = identify_limit_up_stocks(bars_df)
    
    # 4. 运行回测
    results = simple_backtest(df_with_limit)
    
    if results:
        print("\n" + "=" * 50)
        print("回测完成！")
        print("=" * 50)
        
        # 保存结果
        result_path = Path(__file__).parent.parent.parent / "data" / "tushare" / "backtest_results.json"
        import json
        with open(result_path, "w", encoding="utf-8") as f:
            # 转换 datetime 为字符串
            results_copy = results.copy()
            results_copy["trades"] = []
            for trade in results["trades"]:
                trade_copy = trade.copy()
                trade_copy["buy_date"] = str(trade["buy_date"])
                trade_copy["sell_date"] = str(trade["sell_date"])
                results_copy["trades"].append(trade_copy)
            
            json.dump(results_copy, f, indent=2, ensure_ascii=False)
        print(f"结果已保存：{result_path}")


if __name__ == "__main__":
    main()
