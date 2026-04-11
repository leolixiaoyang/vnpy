"""
昨日涨停策略 - 回测脚本
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
import tinyshare as ts

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# 导入配置
from config import (
    TEST_STOCKS, VT_SYMBOLS,
    START_DATE, END_DATE, INITIAL_CAPITAL,
    STRATEGY_PARAMS, DATA_PATH, USE_CACHE,
    TUSHARE_TOKEN, LIMIT_UP_RATES, DEFAULT_LIMIT_UP_RATE, ST_LIMIT_UP_RATE
)


# ========== 数据下载 ==========
def download_data(ts_codes: list, start_date: str, end_date: str) -> pl.DataFrame:
    """下载日线数据"""
    print(f"\n下载数据：{len(ts_codes)} 只股票 ({start_date} - {end_date})")
    
    ts.set_token(TUSHARE_TOKEN)
    pro = ts.pro_api()
    
    all_data = []
    
    for ts_code in ts_codes:
        cache_file = Path(DATA_PATH) / f"{ts_code.replace('.', '_')}.parquet"
        
        if USE_CACHE and cache_file.exists():
            df = pl.read_parquet(cache_file)
            all_data.append(df)
            print(f"  ✓ {ts_code} (缓存)")
            continue
        
        df = pro.daily(ts_code=ts_code, start_date=start_date, end_date=end_date)
        
        if df is not None and len(df) > 0:
            df = pl.DataFrame(df).with_columns(pl.lit(ts_code).alias("ts_code"))
            all_data.append(df)
            
            if USE_CACHE:
                cache_file.parent.mkdir(parents=True, exist_ok=True)
                df.write_parquet(cache_file)
            
            print(f"  ✓ {ts_code}: {len(df)} 条")
    
    if not all_data:
        raise ValueError("没有下载到任何数据")
    
    result = pl.concat(all_data)
    print(f"\n总计：{len(result)} 条记录")
    
    return result


# ========== 涨停识别 ==========
def identify_limit_up(df: pl.DataFrame) -> pl.DataFrame:
    """识别涨停股票"""
    print("\n识别涨停股票...")
    
    def get_limit_rate(ts_code: str) -> float:
        """获取涨停幅度"""
        if "ST" in ts_code:
            return ST_LIMIT_UP_RATE
        
        for prefix, rate in LIMIT_UP_RATES.items():
            if ts_code.startswith(prefix):
                return rate
        
        return DEFAULT_LIMIT_UP_RATE
    
    # 计算涨停价
    df = df.with_columns([
        pl.col("ts_code").map_elements(get_limit_rate, return_dtype=pl.Float64).alias("limit_rate"),
        (pl.col("pre_close") * (1 + pl.col("ts_code").map_elements(get_limit_rate, return_dtype=pl.Float64) - 0.005)).alias("limit_price")
    ])
    
    # 判断涨停
    df = df.with_columns([
        ((pl.col("close") >= pl.col("limit_price")) & 
         (pl.col("close") == pl.col("high"))).alias("is_limit_up")
    ])
    
    # 统计
    limit_up_count = df.filter(pl.col("is_limit_up") == True).height
    print(f"  涨停记录数：{limit_up_count}")
    
    return df


# ========== 信号生成 ==========
def generate_signal(df: pl.DataFrame) -> pl.DataFrame:
    """生成策略信号"""
    print("\n生成信号数据...")
    
    # 转换格式
    signal_df = df.rename({"ts_code": "vt_symbol", "trade_date": "datetime"})
    
    signal_df = signal_df.with_columns([
        pl.col("datetime").str.to_datetime("%Y%m%d"),
        pl.col("vt_symbol").str.to_uppercase()
            .str.replace(".SZ", ".SZSE")
            .str.replace(".SH", ".SSE")
            .alias("vt_symbol"),
        pl.when(pl.col("is_limit_up") == True)
            .then(1.0)
            .otherwise(0.0).alias("signal"),
        (pl.col("close") * pl.col("vol") * 100).alias("market_cap")
    ])
    
    # 选择需要的列
    signal_df = signal_df.select([
        "datetime", "vt_symbol", "signal", "market_cap", "close", "vol"
    ])
    
    # 统计
    signal_count = signal_df.filter(pl.col("signal") > 0).height
    print(f"  涨停信号数：{signal_count}")
    
    return signal_df


# ========== 回测引擎 ==========
class LimitUpBacktestEngine:
    """昨日涨停策略回测引擎"""
    
    def __init__(self, df: pl.DataFrame, signal_df: pl.DataFrame, initial_capital: float, params: dict):
        self.df = df
        self.signal_df = signal_df
        self.initial_capital = initial_capital
        self.params = params
        self.capital = initial_capital
        self.positions = {}  # {vt_symbol: {"volume": x, "cost": y}}
        self.trades = []
        self.holding_days = {}
    
    def run(self) -> dict:
        """运行回测"""
        print(f"\n开始回测...")
        print(f"  初始资金：¥{self.initial_capital:,.2f}")
        print(f"  最大持仓：{self.params['max_positions']}")
        print(f"  止损：-{self.params['stop_loss_rate']*100}%, 止盈：+{self.params['take_profit_rate']*100}%")
        
        # 按日期分组
        dates = sorted(self.df["datetime"].unique())
        
        for i, dt in enumerate(dates):
            # 获取当日数据
            day_df = self.df.filter(pl.col("datetime") == dt)
            bars = {row["vt_symbol"]: row for row in day_df.iter_rows(named=True)}
            
            # 获取当日信号
            signal_df = self.signal_df.filter(pl.col("datetime") == dt)
            
            # 1. 检查持仓止盈止损
            self._check_exit(bars, dt)
            
            # 2. 检查买入信号
            self._check_buy(signal_df, bars, dt)
            
            # 3. 更新持仓天数
            for vt_symbol in list(self.positions.keys()):
                self.holding_days[vt_symbol] = self.holding_days.get(vt_symbol, 0) + 1
        
        # 计算最终结果
        return self._calculate_result()
    
    def _check_exit(self, bars: dict, dt: str):
        """检查止盈止损"""
        for vt_symbol in list(self.positions.keys()):
            if vt_symbol not in bars:
                continue
            
            bar = bars[vt_symbol]
            pos = self.positions[vt_symbol]
            cost_price = pos["cost"]
            current_price = bar["close"]
            
            # 更新最高价
            high_price = pos.get("high", cost_price)
            if bar["high"] > high_price:
                high_price = bar["high"]
                pos["high"] = high_price
            
            profit_rate = (current_price - cost_price) / cost_price
            drawdown = (high_price - current_price) / high_price if high_price > 0 else 0
            hold_days = self.holding_days.get(vt_symbol, 0)
            
            sell = False
            reason = ""
            
            # 止损
            if profit_rate <= -self.params["stop_loss_rate"]:
                sell = True
                reason = "止损"
            
            # 止盈
            elif profit_rate >= self.params["take_profit_rate"]:
                sell = True
                reason = "止盈"
            
            # 回撤止盈
            elif profit_rate > 0 and drawdown >= self.params["trailing_stop_rate"]:
                sell = True
                reason = "回撤止盈"
            
            # 超期
            elif hold_days >= self.params["max_hold_days"]:
                sell = True
                reason = "超期"
            
            if sell:
                self._sell(vt_symbol, bar, dt, reason)
    
    def _check_buy(self, signal_df: pl.DataFrame, bars: dict, dt: str):
        """检查买入信号"""
        # 筛选涨停股票
        limit_up_df = signal_df.filter(pl.col("signal") > 0.5).sort("market_cap", descending=True)
        
        if limit_up_df.is_empty():
            return
        
        # 过滤已持仓
        current_pos = len(self.positions)
        can_buy = self.params["max_positions"] - current_pos
        
        if can_buy <= 0:
            return
        
        # 获取次日开盘价（简化：使用当日收盘价代替）
        buy_candidates = []
        for row in limit_up_df.iter_rows(named=True):
            vt_symbol = row["vt_symbol"]
            if vt_symbol not in self.positions and vt_symbol in bars:
                buy_candidates.append(row)
        
        # 买入前 N 只
        for row in buy_candidates[:can_buy]:
            vt_symbol = row["vt_symbol"]
            price = row["close"]  # 简化：使用收盘价代替次日开盘价
            
            cash = self.capital * 0.95 / can_buy
            volume = int(cash / price / 100) * 100
            
            if volume >= 100:
                self._buy(vt_symbol, price, volume, dt)
    
    def _buy(self, vt_symbol: str, price: float, volume: int, dt: str):
        """买入"""
        cost = volume * price * 1.0003  # 手续费
        if cost > self.capital:
            return
        
        self.capital -= cost
        self.positions[vt_symbol] = {
            "volume": volume,
            "cost": price * 1.0003,
            "high": price
        }
        self.holding_days[vt_symbol] = 0
        
        self.trades.append({
            "date": dt,
            "action": "买入",
            "vt_symbol": vt_symbol,
            "price": price,
            "volume": volume,
            "cost": cost
        })
        
        print(f"  {dt} 买入：{vt_symbol} {volume}股 @ {price:.2f}")
    
    def _sell(self, vt_symbol: str, bar: dict, dt: str, reason: str):
        """卖出"""
        if vt_symbol not in self.positions:
            return
        
        pos = self.positions[vt_symbol]
        volume = pos["volume"]
        cost_price = pos["cost"]
        
        # 简化：使用收盘价代替次日开盘价
        price = bar["close"]
        proceeds = volume * price * 0.9987  # 手续费
        
        profit = proceeds - volume * cost_price
        profit_rate = profit / (volume * cost_price) * 100
        
        self.capital += proceeds
        
        self.trades.append({
            "date": dt,
            "action": "卖出",
            "vt_symbol": vt_symbol,
            "price": price,
            "volume": volume,
            "proceeds": proceeds,
            "profit": profit,
            "profit_rate": profit_rate,
            "reason": reason
        })
        
        print(f"  {dt} {reason}: {vt_symbol} {volume}股 @ {price:.2f}, 盈亏 {profit:,.2f} ({profit_rate:.2f}%)")
        
        self.positions.pop(vt_symbol, None)
        self.holding_days.pop(vt_symbol, None)
    
    def _calculate_result(self) -> dict:
        """计算回测结果"""
        # 最终资金
        final_capital = self.capital
        for vt_symbol, pos in self.positions.items():
            # 按最新收盘价计算
            last_close = self.df.filter(pl.col("vt_symbol") == vt_symbol)["close"][-1]
            final_capital += pos["volume"] * last_close
        
        total_return = (final_capital - self.initial_capital) / self.initial_capital * 100
        
        # 交易统计
        sell_trades = [t for t in self.trades if t["action"] == "卖出"]
        trade_count = len(sell_trades)
        win_trades = [t for t in sell_trades if t.get("profit", 0) > 0]
        win_rate = len(win_trades) / trade_count * 100 if trade_count > 0 else 0
        
        avg_win = sum(t["profit"] for t in win_trades) / len(win_trades) if win_trades else 0
        loss_trades = [t for t in sell_trades if t.get("profit", 0) <= 0]
        avg_loss = sum(t["profit"] for t in loss_trades) / len(loss_trades) if loss_trades else 0
        
        return {
            "initial_capital": self.initial_capital,
            "final_capital": final_capital,
            "total_return": total_return,
            "trade_count": trade_count,
            "win_rate": win_rate,
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "profit_loss_ratio": abs(avg_win / avg_loss) if avg_loss != 0 else 0,
            "trades": self.trades
        }


# ========== 主函数 ==========
def main():
    """主函数"""
    print("=" * 60)
    print("昨日涨停今日买入策略回测")
    print("=" * 60)
    
    # 1. 下载数据
    df = download_data(TEST_STOCKS, START_DATE, END_DATE)
    
    # 2. 识别涨停
    df = identify_limit_up(df)
    
    # 3. 生成信号
    signal_df = generate_signal(df)
    
    # 4. 运行回测
    engine = LimitUpBacktestEngine(df, signal_df, INITIAL_CAPITAL, STRATEGY_PARAMS)
    results = engine.run()
    
    # 5. 输出结果
    print("\n" + "=" * 60)
    print("回测结果")
    print("=" * 60)
    
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
    
    # 6. 保存结果
    output_path = Path(DATA_PATH) / "backtest_results"
    output_path.mkdir(parents=True, exist_ok=True)
    
    import json
    result_file = output_path / f"limit_up_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    
    with open(result_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False, default=str)
    
    print(f"\n结果已保存：{result_file}")
    
    return results


if __name__ == "__main__":
    main()
