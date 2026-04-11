"""
MA5 策略 - 批量回测脚本
======================
对多只股票依次执行 MA5 突破策略回测

作者：Shawn
日期：2026-03-31
"""

import os
import sys
from datetime import datetime
from pathlib import Path

import polars as pl
import tinyshare as ts

# 设置 Tushare
TUSHARE_TOKEN = os.getenv("TUSHARE_TOKEN", "a96ef9108067fe2b72a787c7d0e6a6974e6f05fd43fa3050497acdb4")
ts.set_token(TUSHARE_TOKEN)
pro = ts.pro_api()


# ========== 自选股列表（来自东方财富） ==========
SELF_SELECT_STOCKS = [
    {"ts_code": "600519.SH", "name": "贵州茅台"},
    {"ts_code": "600246.SH", "name": "万通发展"},
    {"ts_code": "000652.SZ", "name": "泰达股份"},
    {"ts_code": "300363.SZ", "name": "博腾股份"},
    {"ts_code": "000651.SZ", "name": "格力电器"},
    {"ts_code": "002349.SZ", "name": "精华制药"},
    {"ts_code": "600521.SH", "name": "华海药业"},
    {"ts_code": "000721.SZ", "name": "西安饮食"},
    {"ts_code": "300059.SZ", "name": "东方财富"},
    {"ts_code": "301383.SZ", "name": "天键股份"},
    {"ts_code": "600280.SH", "name": "中央商场"},
    {"ts_code": "000802.SZ", "name": "北京文化"},
    {"ts_code": "600550.SH", "name": "保变电气"},
    {"ts_code": "600809.SH", "name": "山西汾酒"},
    {"ts_code": "603912.SH", "name": "佳力图"},
    {"ts_code": "002436.SZ", "name": "兴森科技"},
    {"ts_code": "600546.SH", "name": "山煤国际"},
    {"ts_code": "688008.SH", "name": "澜起科技"},
]


# ========== 策略参数 ==========
STRATEGY_PARAMS = {
    "breakout_threshold": 0.01,    # 突破确认阈值 1%
    "stop_loss_rate": 0.10,        # 固定止损 10%
    "volume_ratio": 1.0,           # 成交量倍数
}

START_DATE = "20230101"
END_DATE = "20251231"
INITIAL_CAPITAL = 1000000


# ========== 回测引擎 ==========
class MA5BacktestEngine:
    """MA5 突破策略回测引擎"""
    
    def __init__(self, df: pl.DataFrame, params: dict):
        self.df = df
        self.params = params
        self.capital = INITIAL_CAPITAL
        self.position = 0
        self.cost_price = 0
        self.trades = []
        self.holding = False
        
        self.ma5_history = []
        self.vol_history = []
    
    def run(self) -> dict:
        """运行回测"""
        for i, row in enumerate(self.df.iter_rows(named=True)):
            self._update_history(row)
            
            if i < 5:
                continue
            
            # 计算 MA5
            if len(self.ma5_history) >= 6:
                ma5 = sum(self.ma5_history[-6:-1]) / 5
                vol_ma5 = sum(self.vol_history[-6:-1]) / 5
                prev_ma5 = sum(self.ma5_history[-7:-2]) / 5 if len(self.ma5_history) >= 7 else ma5
            else:
                ma5 = sum(self.ma5_history[:-1]) / len(self.ma5_history[:-1]) if len(self.ma5_history) > 1 else row["close"]
                vol_ma5 = sum(self.vol_history[:-1]) / len(self.vol_history[:-1]) if len(self.vol_history) > 1 else row["vol"]
                prev_ma5 = ma5
            
            prev_row = self.df.row(i-1, named=True)
            
            if self.holding:
                if self.cost_price > 0:
                    current_loss = (row["close"] - self.cost_price) / self.cost_price
                    if current_loss <= -self.params["stop_loss_rate"]:
                        self._sell(row, row["trade_date"], "止损")
                        continue
                
                if row["close"] < ma5:
                    self._sell(row, row["trade_date"], "跌破 MA5")
            else:
                break_up = (row["close"] > ma5) and (prev_row["close"] <= prev_ma5)
                break_confirmed = row["close"] > ma5 * (1 + self.params["breakout_threshold"])
                volume_confirmed = row["vol"] > vol_ma5 * self.params["volume_ratio"]
                
                if break_up and break_confirmed and volume_confirmed:
                    self._buy(row, row["trade_date"], "突破 MA5")
        
        return self._calculate_result()
    
    def _update_history(self, row: dict):
        self.ma5_history.append(row["close"])
        self.vol_history.append(row["vol"])
        
        if len(self.ma5_history) > 6:
            self.ma5_history.pop(0)
            self.vol_history.pop(0)
    
    def _get_next_open(self, trade_date: str) -> float | None:
        next_row = self.df.filter(pl.col("trade_date") > trade_date).limit(1)
        if next_row.is_empty():
            return None
        return next_row["open"][0]
    
    def _buy(self, row: dict, dt: str, reason: str):
        next_open = self._get_next_open(dt)
        if next_open is None:
            return
        
        available_cash = self.capital * (1 - 0.0003)
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
    
    def _sell(self, row: dict, dt: str, reason: str):
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
        
        self.position = 0
        self.cost_price = 0
        self.holding = False
    
    def _calculate_result(self) -> dict:
        final_capital = self.capital
        if self.position > 0:
            last_close = self.df["close"][-1]
            final_capital += self.position * last_close
        
        total_return = (final_capital - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100
        
        sell_trades = [t for t in self.trades if t["action"] == "卖出"]
        trade_count = len(sell_trades)
        win_trades = [t for t in sell_trades if t.get("profit", 0) > 0]
        win_rate = len(win_trades) / trade_count * 100 if trade_count > 0 else 0
        
        avg_win = sum(t["profit"] for t in win_trades) / len(win_trades) if win_trades else 0
        loss_trades = [t for t in sell_trades if t.get("profit", 0) <= 0]
        avg_loss = sum(t["profit"] for t in loss_trades) / len(loss_trades) if loss_trades else 0
        
        # 年化收益率
        days = (datetime.strptime(END_DATE, "%Y%m%d") - datetime.strptime(START_DATE, "%Y%m%d")).days
        years = days / 365.25
        annual_return = ((final_capital / INITIAL_CAPITAL) ** (1 / years) - 1) * 100 if years > 0 else 0
        
        return {
            "initial_capital": INITIAL_CAPITAL,
            "final_capital": final_capital,
            "total_return": total_return,
            "annual_return": annual_return,
            "trade_count": trade_count,
            "win_rate": win_rate,
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "profit_loss_ratio": abs(avg_win / avg_loss) if avg_loss != 0 else 0,
            "trades": self.trades
        }


# ========== 主流程 ==========
def download_data(ts_code: str, start_date: str, end_date: str) -> pl.DataFrame:
    """下载日线数据"""
    df = pro.daily(ts_code=ts_code, start_date=start_date, end_date=end_date)
    if df is None or len(df) == 0:
        return None
    return pl.DataFrame(df).sort("trade_date")


def main():
    """主函数"""
    print("=" * 80)
    print("MA5 突破策略 - 批量回测")
    print("=" * 80)
    print(f"\n回测期：{START_DATE} - {END_DATE}")
    print(f"初始资金：¥{INITIAL_CAPITAL:,.2f}")
    print(f"股票数量：{len(SELF_SELECT_STOCKS)}")
    print(f"策略参数：突破{STRATEGY_PARAMS['breakout_threshold']*100}%，止损-{STRATEGY_PARAMS['stop_loss_rate']*100}%")
    
    all_results = []
    
    for i, stock in enumerate(SELF_SELECT_STOCKS):
        print(f"\n[{i+1}/{len(SELF_SELECT_STOCKS)}] {stock['name']} ({stock['ts_code']})")
        print("-" * 60)
        
        try:
            # 下载数据
            df = download_data(stock["ts_code"], START_DATE, END_DATE)
            
            if df is None or len(df) < 10:
                print(f"  ✗ 数据不足，跳过")
                continue
            
            print(f"  数据：{len(df)} 条")
            
            # 运行回测
            engine = MA5BacktestEngine(df, STRATEGY_PARAMS)
            results = engine.run()
            
            # 保存结果
            results["stock_name"] = stock["name"]
            results["ts_code"] = stock["ts_code"]
            all_results.append(results)
            
            # 输出摘要
            print(f"  总收益：{results['total_return']:.2f}%")
            print(f"  年化：{results['annual_return']:.2f}%")
            print(f"  交易：{results['trade_count']} 次，胜率 {results['win_rate']:.1f}%")
            
        except Exception as e:
            print(f"  ✗ 错误：{e}")
            all_results.append({
                "stock_name": stock["name"],
                "ts_code": stock["ts_code"],
                "error": str(e)
            })
    
    # 汇总统计
    print("\n" + "=" * 80)
    print("回测汇总")
    print("=" * 80)
    
    valid_results = [r for r in all_results if "error" not in r]
    
    if valid_results:
        # 按收益率排序
        sorted_results = sorted(valid_results, key=lambda x: x["total_return"], reverse=True)
        
        print("\n收益率排名（前 5）:")
        for i, r in enumerate(sorted_results[:5]):
            print(f"  {i+1}. {r['stock_name']}: {r['total_return']:.2f}%")
        
        print("\n收益率排名（后 5）:")
        for i, r in enumerate(sorted_results[-5:]):
            print(f"  {i+1}. {r['stock_name']}: {r['total_return']:.2f}%")
        
        # 平均统计
        avg_return = sum(r["total_return"] for r in valid_results) / len(valid_results)
        avg_annual = sum(r["annual_return"] for r in valid_results) / len(valid_results)
        avg_win_rate = sum(r["win_rate"] for r in valid_results) / len(valid_results)
        
        print(f"\n平均统计:")
        print(f"  平均总收益：{avg_return:.2f}%")
        print(f"  平均年化：{avg_annual:.2f}%")
        print(f"  平均胜率：{avg_win_rate:.1f}%")
    
    # 保存结果
    output_path = Path("data/tushare/backtest_results")
    output_path.mkdir(parents=True, exist_ok=True)
    
    import json
    result_file = output_path / f"ma5_batch_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    
    with open(result_file, "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=2, ensure_ascii=False, default=str)
    
    print(f"\n结果已保存：{result_file}")
    
    return all_results


if __name__ == "__main__":
    results = main()
