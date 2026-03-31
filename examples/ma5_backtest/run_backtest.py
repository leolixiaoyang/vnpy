"""
MA5 突破策略 - 回测脚本
======================
运行此脚本执行策略回测

作者：Shawn
日期：2026-03-31
"""

import os
import sys
from datetime import datetime
from pathlib import Path

import polars as pl
import tushare as ts

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# 导入配置
from config import (
    VT_SYMBOL, TS_CODE, STOCK_NAME,
    START_DATE, END_DATE, INITIAL_CAPITAL,
    STRATEGY_PARAMS, DATA_PATH, USE_CACHE
)

# 导入策略
from vnpy.strategies.ma5_strategy import MA5BreakoutStrategy


# ========== 数据下载 ==========
def download_data(ts_code: str, start_date: str, end_date: str) -> pl.DataFrame:
    """下载日线数据"""
    print(f"\n下载数据：{ts_code} ({start_date} - {end_date})")
    
    # 检查缓存
    cache_file = Path(DATA_PATH) / f"{ts_code.replace('.', '_')}.parquet"
    
    if USE_CACHE and cache_file.exists():
        print(f"  使用缓存数据：{cache_file}")
        return pl.read_parquet(cache_file)
    
    # 下载新数据
    TUSHARE_TOKEN = os.getenv("TUSHARE_TOKEN", "a96ef9108067fe2b72a787c7d0e6a6974e6f05fd43fa3050497acdb4")
    ts.set_token(TUSHARE_TOKEN)
    pro = ts.pro_api()
    
    df = pro.daily(ts_code=ts_code, start_date=start_date, end_date=end_date)
    
    if df is None or len(df) == 0:
        raise ValueError(f"没有下载到数据：{ts_code}")
    
    df = pl.DataFrame(df).sort("trade_date")
    
    # 保存缓存
    if USE_CACHE:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        df.write_parquet(cache_file)
        print(f"  已保存缓存：{cache_file}")
    
    print(f"  ✓ 下载 {len(df)} 条记录")
    
    return df


# ========== 回测引擎 ==========
class SimpleBacktestEngine:
    """简化版回测引擎（不依赖 vnpy alpha）"""
    
    def __init__(self, df: pl.DataFrame, initial_capital: float, params: dict):
        self.df = df
        self.initial_capital = initial_capital
        self.params = params
        self.capital = initial_capital
        self.position = 0
        self.cost_price = 0
        self.trades = []
        self.holding = False
        
        # 指标缓存
        self.ma5_history = []
        self.vol_history = []
    
    def run(self) -> dict:
        """运行回测"""
        print(f"\n开始回测...")
        print(f"  初始资金：¥{self.initial_capital:,.2f}")
        print(f"  突破阈值：{self.params['breakout_threshold']*100}%")
        print(f"  止损：-{self.params['stop_loss_rate']*100}%")
        
        for i, row in enumerate(self.df.iter_rows(named=True)):
            # 更新历史数据
            self._update_history(row)
            
            # 跳过前 5 天（MA5 未形成）
            if i < 5:
                continue
            
            # 计算当前 MA5（前 5 日收盘价的均值，不包含当日）
            if len(self.ma5_history) >= 6:
                ma5 = sum(self.ma5_history[-6:-1]) / 5  # 前 5 日（排除最新）
                vol_ma5 = sum(self.vol_history[-6:-1]) / 5
                prev_ma5 = sum(self.ma5_history[-7:-2]) / 5 if len(self.ma5_history) >= 7 else ma5
            else:
                ma5 = sum(self.ma5_history[:-1]) / len(self.ma5_history[:-1]) if len(self.ma5_history) > 1 else row["close"]
                vol_ma5 = sum(self.vol_history[:-1]) / len(self.vol_history[:-1]) if len(self.vol_history) > 1 else row["vol"]
                prev_ma5 = ma5
            
            # 获取前一日数据
            prev_row = self.df.row(i-1, named=True)
            
            # 检查持仓
            if self.holding:
                # 检查止损
                if self.cost_price > 0:
                    current_loss = (row["close"] - self.cost_price) / self.cost_price
                    if current_loss <= -self.params["stop_loss_rate"]:
                        self._sell(row, row["trade_date"], "止损")
                        continue
                
                # 检查卖出信号
                if row["close"] < ma5:
                    self._sell(row, row["trade_date"], "跌破 MA5")
            
            else:
                # 检查买入信号
                break_up = (row["close"] > ma5) and (prev_row["close"] <= prev_ma5)
                break_confirmed = row["close"] > ma5 * (1 + self.params["breakout_threshold"])
                volume_confirmed = row["vol"] > vol_ma5 * self.params["volume_ratio"]
                
                # 调试输出（前 10 次）
                if i < 10:
                    print(f"  Day {i}: close={row['close']:.2f}, ma5={ma5:.2f}, prev_close={prev_row['close']:.2f}, prev_ma5={prev_ma5:.2f}, break_up={break_up}, confirmed={break_confirmed}, vol={volume_confirmed}")
                
                if break_up and break_confirmed and volume_confirmed:
                    self._buy(row, row["trade_date"], "突破 MA5")
        
        # 计算最终结果
        return self._calculate_result()
    
    def _update_history(self, row: dict):
        """更新历史数据"""
        self.ma5_history.append(row["close"])
        self.vol_history.append(row["vol"])
        
        # 保持最近 6 条（用于计算前一日 MA5）
        if len(self.ma5_history) > 6:
            self.ma5_history.pop(0)
            self.vol_history.pop(0)
    
    def _get_next_open(self, trade_date: str) -> float | None:
        """获取次日开盘价"""
        next_row = self.df.filter(pl.col("trade_date") > trade_date).limit(1)
        if next_row.is_empty():
            return None
        return next_row["open"][0]
    
    def _buy(self, row: dict, dt: str, reason: str):
        """买入"""
        next_open = self._get_next_open(dt)
        if next_open is None:
            return
        
        # 全仓买入
        available_cash = self.capital * (1 - 0.0003)  # 手续费
        volume = int(available_cash / next_open / 100) * 100
        
        if volume < 100:
            return
        
        cost = volume * next_open * 1.0003
        self.capital -= cost
        self.position = volume
        self.cost_price = next_open * 1.0003
        self.holding = True
        
        self.trades.append({
            "date": dt,
            "action": "买入",
            "price": next_open,
            "volume": volume,
            "cost": cost,
            "reason": reason
        })
        
        print(f"  {dt} {reason}: 买入 {volume}股 @ {next_open:.2f}")
    
    def _sell(self, row: dict, dt: str, reason: str):
        """卖出"""
        if self.position <= 0:
            return
        
        next_open = self._get_next_open(dt)
        if next_open is None:
            return
        
        proceeds = self.position * next_open * (1 - 0.0013)
        profit = proceeds - self.position * self.cost_price
        profit_rate = profit / (self.position * self.cost_price) * 100
        
        self.capital += proceeds
        
        self.trades.append({
            "date": dt,
            "action": "卖出",
            "price": next_open,
            "volume": self.position,
            "proceeds": proceeds,
            "profit": profit,
            "profit_rate": profit_rate,
            "reason": reason
        })
        
        print(f"  {dt} {reason}: 卖出 {self.position}股 @ {next_open:.2f}, 盈亏 {profit:,.2f} ({profit_rate:.2f}%)")
        
        self.position = 0
        self.cost_price = 0
        self.holding = False
    
    def _calculate_result(self) -> dict:
        """计算回测结果"""
        # 计算最终资金
        final_capital = self.capital
        if self.position > 0:
            last_close = self.df["close"][-1]
            final_capital += self.position * last_close
        
        total_return = (final_capital - self.initial_capital) / self.initial_capital * 100
        
        # 交易统计
        sell_trades = [t for t in self.trades if t["action"] == "卖出"]
        trade_count = len(sell_trades)
        win_trades = [t for t in sell_trades if t.get("profit", 0) > 0]
        win_rate = len(win_trades) / trade_count * 100 if trade_count > 0 else 0
        
        # 盈亏统计
        avg_win = sum(t["profit"] for t in win_trades) / len(win_trades) if win_trades else 0
        loss_trades = [t for t in sell_trades if t.get("profit", 0) <= 0]
        avg_loss = sum(t["profit"] for t in loss_trades) / len(loss_trades) if loss_trades else 0
        
        # 最大回撤
        peak = self.initial_capital
        max_drawdown = 0
        capital = self.initial_capital
        
        for trade in self.trades:
            if trade["action"] == "卖出":
                capital = trade["proceeds"] + (self.position * self.cost_price if self.position > 0 else 0)
                if capital > peak:
                    peak = capital
                drawdown = (peak - capital) / peak * 100
                if drawdown > max_drawdown:
                    max_drawdown = drawdown
        
        return {
            "stock": STOCK_NAME,
            "period": f"{START_DATE} - {END_DATE}",
            "initial_capital": self.initial_capital,
            "final_capital": final_capital,
            "total_return": total_return,
            "trade_count": trade_count,
            "win_rate": win_rate,
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "profit_loss_ratio": abs(avg_win / avg_loss) if avg_loss != 0 else 0,
            "max_drawdown": max_drawdown,
            "trades": self.trades
        }


# ========== 主函数 ==========
def main():
    """主函数"""
    print("=" * 60)
    print(f"MA5 突破策略回测 - {STOCK_NAME}")
    print("=" * 60)
    
    # 1. 下载数据
    df = download_data(TS_CODE, START_DATE, END_DATE)
    
    # 2. 运行回测
    engine = SimpleBacktestEngine(df, INITIAL_CAPITAL, STRATEGY_PARAMS)
    results = engine.run()
    
    # 3. 输出结果
    print("\n" + "=" * 60)
    print("回测结果")
    print("=" * 60)
    
    print(f"\n基本信息:")
    print(f"  股票：{results['stock']}")
    print(f"  回测期：{results['period']}")
    
    print(f"\n资金情况:")
    print(f"  初始资金：¥{results['initial_capital']:,.2f}")
    print(f"  最终资金：¥{results['final_capital']:,.2f}")
    print(f"  总收益率：{results['total_return']:.2f}%")
    
    print(f"\n交易统计:")
    print(f"  交易次数：{results['trade_count']}")
    print(f"  胜率：{results['win_rate']:.2f}%")
    print(f"  平均盈利：¥{results['avg_win']:,.2f}")
    print(f"  平均亏损：¥{results['avg_loss']:,.2f}")
    print(f"  盈亏比：{results['profit_loss_ratio']:.2f}:1")
    print(f"  最大回撤：{results['max_drawdown']:.2f}%")
    
    # 4. 保存结果
    output_path = Path(DATA_PATH) / "backtest_results"
    output_path.mkdir(parents=True, exist_ok=True)
    
    import json
    result_file = output_path / f"ma5_{TS_CODE.replace('.', '_')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    
    with open(result_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False, default=str)
    
    print(f"\n结果已保存：{result_file}")
    
    return results


if __name__ == "__main__":
    main()
