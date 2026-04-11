"""简化版小市值策略回测 - 使用 pandas"""

import sys
from pathlib import Path

ROOT = Path("/home/admin/.openclaw/workspace/vnpy")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).parent))

import tinyshare as ts
import pandas as pd
import numpy as np
from datetime import datetime
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

# 配置
TUSHARE_TOKEN = "bNP3yb6kn4CCht3IGVh96GjeRvh72t78FWDwPFe0n2yF2X0w89KsSFjOc54c8a35"
START_DATE = "20180101"
END_DATE = "20260410"
INITIAL_CAPITAL = 1_000_000

# 简化股票池 - 从中证1000动态获取，但限制数量
INDEX_CODE = "000852.SH"  # 中证1000
MAX_STOCKS = 50  # 限制拉取数量，避免内存问题

def download_data():
    """下载所有数据"""
    ts.set_token(TUSHARE_TOKEN)
    pro = ts.pro_api()
    
    # 动态获取中证1000成分股
    print(f"获取 {INDEX_CODE} 成分股...")
    df_index = pro.index_weight(index_code=INDEX_CODE, start_date="20240101")
    latest_date = df_index['trade_date'].max()
    latest_df = df_index[df_index['trade_date'] == latest_date]
    stock_pool = list(latest_df['con_code'].unique())[:MAX_STOCKS]
    print(f"股票池: {len(stock_pool)} 只 (中证1000前{MAX_STOCKS}只)")
    
    frames = []
    
    # 下载股票数据
    print("下载股票数据...")
    for i, ts_code in enumerate(stock_pool):
        print(f"  {i+1}/{len(stock_pool)} {ts_code}")
        try:
            df = pro.daily(ts_code=ts_code, start_date=START_DATE, end_date=END_DATE)
            if len(df) > 0:
                # 获取基本面数据
                try:
                    basic = pro.daily_basic(ts_code=ts_code, start_date=START_DATE, end_date=END_DATE,
                                           fields="ts_code,trade_date,pe,pb,total_mv,circ_mv")
                    if len(basic) > 0:
                        df = df.merge(basic, on=["ts_code", "trade_date"], how="left")
                except:
                    pass
                
                df["market_cap"] = df.get("circ_mv", df["close"] * df["vol"] * 100)
                frames.append(df)
        except Exception as e:
            print(f"    跳过: {e}")
            continue
    
    # 下载黄金ETF
    print("下载黄金ETF...")
    etf_df = pro.fund_daily(ts_code="518880.SH", start_date=START_DATE, end_date=END_DATE)
    print(f"  ETF: {len(etf_df)} 条")
    
    # 合并所有股票数据
    all_stocks = pd.concat(frames, ignore_index=True)
    etf_df = pd.DataFrame(etf_df)
    
    return all_stocks, etf_df

def simulate_strategy(stock_df, etf_df):
    """简单的回测模拟 - 小市值+黄金ETF杠铃策略"""
    stock_df = stock_df.sort_values("trade_date")
    
    # 所有交易日
    all_dates = sorted(stock_df["trade_date"].unique().tolist())
    
    # 每7天调仓（模拟策略的调仓周期）
    rebalance_dates = all_dates[::7]
    
    balance = INITIAL_CAPITAL
    stock_ratio = 0.5
    etf_ratio = 0.5
    
    results = []
    prev_positions = []
    
    for i, date in enumerate(rebalance_dates):
        day_stocks = stock_df[stock_df["trade_date"] == date]
        
        if len(day_stocks) == 0:
            continue
        
        # 按市值排序，选最小的3只（简化）
        small_caps = day_stocks.sort_values("market_cap").head(3)
        current_positions = small_caps["ts_code"].tolist()
        
        # 计算收益
        if i > 0 and len(prev_positions) > 0:
            prev_date = rebalance_dates[i-1]
            
            # 股票收益
            stock_return = 0
            for ts_code in prev_positions[:3]:
                curr = day_stocks[day_stocks["ts_code"] == ts_code]
                prev = stock_df[(stock_df["trade_date"] == prev_date) & (stock_df["ts_code"] == ts_code)]
                if len(curr) > 0 and len(prev) > 0:
                    pct_chg = float(curr["pct_chg"].tolist()[0])
                    stock_return += pct_chg / 100 * stock_ratio / 3
            
            # ETF收益
            etf_return = 0
            curr_etf = etf_df[etf_df["trade_date"] == date]
            prev_etf = etf_df[etf_df["trade_date"] == prev_date]
            if len(curr_etf) > 0 and len(prev_etf) > 0:
                etf_pct = float(curr_etf["pct_chg"].tolist()[0])
                etf_return = etf_pct / 100 * etf_ratio
            
            # 总收益
            total_return = stock_return + etf_return
            balance = balance * (1 + total_return)
        
        results.append({
            "date": str(date),
            "balance": balance,
            "positions": ",".join(current_positions[:3])
        })
        
        prev_positions = current_positions
    
    return pd.DataFrame(results)

def main():
    print("=" * 50)
    print("小市值杠铃策略 - 简化回测")
    print("=" * 50)
    print(f"股票池来源: {INDEX_CODE} (中证1000)")
    print(f"时间范围: 2018-01 ~ 2026-04")
    print(f"初始资金: {INITIAL_CAPITAL}")
    print(f"配置: 50%股票 + 50%黄金ETF")
    print("=" * 50)
    
    # 下载数据
    stock_df, etf_df = download_data()
    print(f"\n股票数据: {len(stock_df)} 条")
    print(f"ETF数据: {len(etf_df)} 条")
    
    # 运行回测
    print("\n运行回测...")
    results = simulate_strategy(stock_df, etf_df)
    
    # 计算统计
    start_balance = results["balance"].iloc[0]
    end_balance = results["balance"].iloc[-1]
    total_return = (end_balance / start_balance - 1) * 100
    years = 8.3
    annual_return = ((end_balance / start_balance) ** (1/years) - 1) * 100
    
    # 最大回撤
    balances = results["balance"].tolist()
    peak = balances[0]
    max_drawdown = 0
    for b in balances:
        if b > peak:
            peak = b
        drawdown = (peak - b) / peak
        if drawdown > max_drawdown:
            max_drawdown = drawdown
    
    print("\n" + "=" * 50)
    print("回测统计结果")
    print("=" * 50)
    print(f"初始资金: {start_balance:,.0f}")
    print(f"最终资金: {end_balance:,.0f}")
    print(f"总收益率: {total_return:.2f}%")
    print(f"年化收益率: {annual_return:.2f}%")
    print(f"最大回撤: {max_drawdown*100:.2f}%")
    print("=" * 50)
    
    # 保存结果
    output_dir = Path("/home/admin/.openclaw/workspace/vnpy/lab_data/small_cap")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    results.to_csv(output_dir / "simple_backtest_result.csv", index=False)
    
    # 画图
    fig, ax = plt.subplots(figsize=(12, 6))
    ax.plot(range(len(results)), results["balance"], linewidth=2, color='#1f77b4')
    ax.set_title("小市值杠铃策略净值曲线 (2018-2026)")
    ax.set_xlabel("调仓次数")
    ax.set_ylabel("账户余额")
    ax.grid(True, alpha=0.3)
    
    # 标注关键数据
    ax.text(0.02, 0.98, f"总收益: {total_return:.1f}%\n年化: {annual_return:.1f}%\n最大回撤: {max_drawdown*100:.1f}%",
            transform=ax.transAxes, fontsize=10, verticalalignment='top',
            bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))
    
    plt.tight_layout()
    plt.savefig(output_dir / "equity_curve.png", dpi=150)
    print(f"\n图表已保存: {output_dir / 'equity_curve.png'}")
    print(f"数据已保存: {output_dir / 'simple_backtest_result.csv'}")
    
    return results, {
        "total_return": total_return,
        "annual_return": annual_return,
        "max_drawdown": max_drawdown * 100,
        "start_balance": start_balance,
        "end_balance": end_balance
    }

if __name__ == "__main__":
    results, stats = main()