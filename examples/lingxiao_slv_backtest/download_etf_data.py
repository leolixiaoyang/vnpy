"""手动下载 ETF 数据脚本。

由于服务器网络限制，可能需要手动运行此脚本获取数据。
支持多种数据源备选。
"""

from __future__ import annotations

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


def download_from_tushare(symbol: str, exchange: str = "SSE") -> pl.DataFrame | None:
    """从 tushare 获取 ETF 数据（使用自定义 API）。"""
    try:
        import tushare as ts
    except ImportError:
        print("tushare 未安装")
        return None
    
    print(f"尝试 tushare 获取 {symbol}...")
    
    # tushare token 和自定义 API
    token = "46bccdd833f7437fc6cf7a65f1c2190b56520905f08758b30213a097f9a3"
    pro = ts.pro_api(token)
    pro._DataApi__token = token
    pro._DataApi__http_url = 'http://lianghua.nanyangqiankun.top'
    
    # 交易所代码映射
    ts_exchange = "SH" if exchange == "SSE" else "SZ"
    ts_code = f"{symbol}.{ts_exchange}"
    
    try:
        start_date = START_DATE.replace("-", "")
        end_date = END_DATE.replace("-", "")
        
        # 尝试 fund_daily 接口
        raw_df = pro.fund_daily(
            ts_code=ts_code,
            start_date=start_date,
            end_date=end_date,
        )
        
        if raw_df is None or len(raw_df) == 0:
            # 尝试 daily 接口
            raw_df = pro.daily(
                ts_code=ts_code,
                start_date=start_date,
                end_date=end_date,
            )
        
        if raw_df is not None and len(raw_df) > 0:
            raw_df = raw_df.rename(columns={
                "trade_date": "datetime",
                "open": "open",
                "close": "close",
                "high": "high",
                "low": "low",
                "vol": "volume",
            })
            
            raw_df["datetime"] = raw_df["datetime"].apply(
                lambda x: datetime.strptime(str(x), "%Y%m%d")
            )
            
            raw_df = raw_df.sort_values("datetime")
            
            df = pl.DataFrame(
                raw_df[["datetime", "open", "high", "low", "close", "volume"]]
                .to_dict("list")
            )
            
            start_dt = datetime.fromisoformat(START_DATE)
            end_dt = datetime.fromisoformat(END_DATE)
            df = df.filter(
                (pl.col("datetime") >= start_dt) &
                (pl.col("datetime") <= end_dt)
            )
            
            print(f"  成功: {len(df)} 条数据")
            return df
            
    except Exception as e:
        print(f"  失败: {e}")
        
    return None





def download_from_ef(symbol: str, market: int = 1) -> pl.DataFrame | None:
    """从 EF (东方财富备用接口) 获取数据。"""
    import requests
    import json
    
    print(f"尝试 EF 接口获取 {symbol}...")
    
    url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
    params = {
        "secid": f"{market}.{symbol}",
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58",
        "klt": 101,
        "fqt": 1,
        "end": "20500101",
        "lmt": 2000,
    }
    
    try:
        resp = requests.get(url, params=params, timeout=30)
        text = resp.text
        
        # 尝试解析 JSON 或 JSONP
        if text.startswith("{"):
            data = json.loads(text)
        elif "(" in text:
            json_str = text.split("(")[1].rstrip(");")
            data = json.loads(json_str)
        else:
            print(f"  无法解析响应: {text[:100]}")
            return None
            
        if data.get("data") and data["data"].get("klines"):
            klines = data["data"]["klines"]
            rows = []
            for k in klines:
                parts = k.split(",")
                rows.append({
                    "datetime": datetime.strptime(parts[0], "%Y-%m-%d"),
                    "open": float(parts[1]),
                    "close": float(parts[2]),
                    "high": float(parts[3]),
                    "low": float(parts[4]),
                    "volume": float(parts[5]),
                })
            
            df = pl.DataFrame(rows).sort("datetime")
            
            start_dt = datetime.fromisoformat(START_DATE)
            end_dt = datetime.fromisoformat(END_DATE)
            df = df.filter(
                (pl.col("datetime") >= start_dt) & 
                (pl.col("datetime") <= end_dt)
            )
            
            print(f"  成功: {len(df)} 条数据")
            return df
            
    except Exception as e:
        print(f"  失败: {e}")
        
    return None


def download_from_sina(symbol: str, market: str = "sh") -> pl.DataFrame | None:
    """从新浪财经获取数据。"""
    import requests
    
    print(f"尝试新浪接口获取 {symbol}...")
    
    url = f"http://finance.sina.com.cn/realstock/company/{market}{symbol}/hisdata.shtml"
    
    try:
        # 新浪接口可能需要其他方式
        # 使用备用方式：直接获取 CSV
        csv_url = f"http://quotes.money.163.com/service/chddata_{market}{symbol}.csv"
        resp = requests.get(csv_url, timeout=30)
        
        if resp.status_code == 200:
            import csv
            from io import StringIO
            
            reader = csv.DictReader(StringIO(resp.text))
            rows = []
            for row in reader:
                try:
                    rows.append({
                        "datetime": datetime.strptime(row["日期"], "%Y-%m-%d"),
                        "open": float(row["开盘价"]),
                        "close": float(row["收盘价"]),
                        "high": float(row["最高价"]),
                        "low": float(row["最低价"]),
                        "volume": float(row["成交量"]),
                    })
                except (KeyError, ValueError):
                    continue
            
            if rows:
                df = pl.DataFrame(rows).sort("datetime")
                start_dt = datetime.fromisoformat(START_DATE)
                end_dt = datetime.fromisoformat(END_DATE)
                df = df.filter(
                    (pl.col("datetime") >= start_dt) & 
                    (pl.col("datetime") <= end_dt)
                )
                print(f"  成功: {len(df)} 条数据")
                return df
                
    except Exception as e:
        print(f"  失败: {e}")
        
    return None


def save_to_lab(lab: AlphaLab, vt_symbol: str, df: pl.DataFrame) -> None:
    """保存数据到 AlphaLab。"""
    symbol, exchange_str = vt_symbol.split(".")
    exchange = Exchange[exchange_str]
    
    bars = []
    for row in df.to_dicts():
        bar = BarData(
            symbol=symbol,
            exchange=exchange,
            datetime=row["datetime"],
            interval=INTERVAL,
            open_price=float(row["open"]),
            high_price=float(row["high"]),
            low_price=float(row["low"]),
            close_price=float(row["close"]),
            volume=float(row["volume"]),
            gateway_name="DB",
        )
        bars.append(bar)
    
    lab.save_bar_data(bars)
    print(f"已保存 {len(bars)} 条数据到 AlphaLab")


def main():
    """主函数。"""
    lab = AlphaLab(str(LAB_PATH))
    
    all_symbols = {"target": VT_SYMBOL}
    all_symbols.update(REFERENCE_SYMBOLS)
    
    # 交易所映射
    exchange_map = {
        "SSE": "SSE",
        "SZSE": "SZSE",
    }
    
    success_count = 0
    
    for alias, vt_symbol in all_symbols.items():
        print(f"\n{'='*50}")
        print(f"处理 {alias}: {vt_symbol}")
        
        # 检查是否已有数据
        bars = lab.load_bar_data(
            vt_symbol,
            INTERVAL,
            START_DATE,
            END_DATE,
        )
        
        if bars:
            print(f"已有 {len(bars)} 条数据，跳过")
            success_count += 1
            continue
        
        symbol, exchange_str = vt_symbol.split(".")
        exchange = exchange_map.get(exchange_str, "SSE")
        
        # 尝试多个数据源（优先 tushare）
        df = None
        
        # 1. tushare
        df = download_from_tushare(symbol, exchange)
        
        # 3. 东方财富备用
        if df is None:
            market = 1 if exchange == "SSE" else 0
            df = download_from_ef(symbol, market)
        
        # 4. 新浪/网易
        if df is None:
            prefix = "sh" if exchange == "SSE" else "sz"
            df = download_from_sina(symbol, prefix)
        
        if df is not None:
            save_to_lab(lab, vt_symbol, df)
            success_count += 1
        else:
            print(f"所有数据源均失败，请手动获取 {vt_symbol} 数据")
    
    print(f"\n{'='*50}")
    print(f"完成: {success_count}/{len(all_symbols)} 个品种数据就绪")
    
    if success_count < len(all_symbols):
        print("\n备选方案:")
        print("1. 手动从东方财富/同花顺下载 CSV 数据")
        print("2. 运行: python import_csv_data.py --sample 使用模拟数据测试")


if __name__ == "__main__":
    main()