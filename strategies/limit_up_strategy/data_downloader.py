"""
Tushare 数据下载脚本
====================
用于下载 A 股日线数据和股票基本信息，生成策略所需的信号数据

使用前请确保：
1. 已安装 tushare: pip install tushare
2. 已设置 TUSHARE_TOKEN 环境变量或在代码中配置

作者：Shawn
日期：2026-03-31
"""

import os
from datetime import datetime, timedelta
from pathlib import Path

import polars as pl
import tushare as ts


class TushareDataDownloader:
    """Tushare 数据下载器"""

    def __init__(self, token: str | None = None):
        """
        初始化
        
        Args:
            token: Tushare token，如不提供则从环境变量读取
        """
        self.token = token or os.getenv("TUSHARE_TOKEN")
        
        if not self.token:
            raise ValueError("请设置 TUSHARE_TOKEN 环境变量或在代码中传入 token")
        
        # 初始化 Tushare
        ts.set_token(self.token)
        self.pro = ts.pro_api()
        
        # 数据保存路径
        self.data_path = Path(__file__).parent.parent.parent / "data" / "tushare"
        self.data_path.mkdir(parents=True, exist_ok=True)
        
        print(f"数据保存路径：{self.data_path}")

    def download_stock_basic(self) -> pl.DataFrame:
        """
        下载股票基本信息
        
        Returns:
            股票信息 DataFrame
        """
        print("正在下载股票基本信息...")
        
        # 下载股票列表
        df = self.pro.stock_basic(
            exchange='',
            list_status='L',
            fields='ts_code,symbol,name,area,industry,market,list_date,act_shares'
        )
        
        # 转换为 Polars DataFrame
        df = pl.DataFrame(df)
        
        # 计算市值（收盘价需要后续更新）
        # 这里先保存基本信息
        df = df.with_columns([
            pl.col("act_shares").alias("total_shares"),  # 总股本（万股）
        ])
        
        # 保存
        save_path = self.data_path / "stock_basic.parquet"
        df.write_parquet(save_path)
        print(f"股票基本信息已保存：{save_path}, 共 {len(df)} 只股票")
        
        return df

    def download_daily_data(
        self,
        ts_code: str,
        start_date: str,
        end_date: str
    ) -> pl.DataFrame:
        """
        下载单只股票的日线数据
        
        Args:
            ts_code: Tushare 股票代码（如 000001.SZ）
            start_date: 开始日期（YYYYMMDD）
            end_date: 结束日期（YYYYMMDD）
            
        Returns:
            日线数据 DataFrame
        """
        df = self.pro.daily(
            ts_code=ts_code,
            start_date=start_date,
            end_date=end_date
        )
        
        if df is None or len(df) == 0:
            return pl.DataFrame()
        
        df = pl.DataFrame(df)
        
        # 重命名和整理字段
        df = df.rename({
            "trade_date": "trade_date",
            "open": "open",
            "high": "high",
            "low": "low",
            "close": "close",
            "pre_close": "pre_close",
            "change": "change",
            "pct_chg": "pct_chg",
            "vol": "volume",
            "amount": "turnover"
        })
        
        return df

    def download_all_daily(
        self,
        start_date: str,
        end_date: str,
        ts_codes: list[str] | None = None
    ) -> pl.DataFrame:
        """
        批量下载日线数据
        
        Args:
            start_date: 开始日期（YYYYMMDD）
            end_date: 结束日期（YYYYMMDD）
            ts_codes: 股票代码列表，如不提供则下载全部
            
        Returns:
            合并的日线数据 DataFrame
        """
        if ts_codes is None:
            # 读取股票列表
            basic_path = self.data_path / "stock_basic.parquet"
            if not basic_path.exists():
                self.download_stock_basic()
            
            stock_basic = pl.read_parquet(basic_path)
            ts_codes = list(stock_basic["ts_code"])
        
        print(f"开始下载 {len(ts_codes)} 只股票的日线数据...")
        
        all_data = []
        
        for i, ts_code in enumerate(ts_codes):
            try:
                df = self.download_daily_data(ts_code, start_date, end_date)
                if not df.is_empty():
                    df = df.with_columns(pl.lit(ts_code).alias("ts_code"))
                    all_data.append(df)
                
                if (i + 1) % 100 == 0:
                    print(f"已下载 {i + 1}/{len(ts_codes)} 只股票")
                    
            except Exception as e:
                print(f"下载失败 {ts_code}: {e}")
        
        if not all_data:
            return pl.DataFrame()
        
        # 合并所有数据
        result = pl.concat(all_data)
        
        # 保存
        save_path = self.data_path / f"daily_{start_date}_{end_date}.parquet"
        result.write_parquet(save_path)
        print(f"日线数据已保存：{save_path}, 共 {len(result)} 条记录")
        
        return result

    def identify_limit_up(self, df: pl.DataFrame) -> pl.DataFrame:
        """
        识别涨停股票
        
        Args:
            df: 日线数据 DataFrame（包含 pre_close, close, high 字段）
            
        Returns:
            添加 is_limit_up 字段的 DataFrame
        """
        # 根据股票代码判断涨停幅度
        def get_limit_rate(ts_code: str) -> float:
            """获取涨停幅度"""
            # 科创板
            if ts_code.startswith("688"):
                return 0.20
            # 创业板
            elif ts_code.startswith("300"):
                return 0.20
            # 北交所
            elif ts_code.startswith("8") or ts_code.startswith("4") or ts_code.startswith("920"):
                return 0.30
            # ST 股票
            elif "ST" in ts_code:
                return 0.05
            # 主板
            else:
                return 0.10
        
        # 计算涨停价
        df = df.with_columns([
            pl.col("ts_code").map_elements(get_limit_rate, return_dtype=pl.Float64).alias("limit_rate"),
            (pl.col("pre_close") * (1 + pl.col("ts_code").map_elements(get_limit_rate, return_dtype=pl.Float64) - 0.005)).alias("limit_price")
        ])
        
        # 判断涨停：收盘价 >= 涨停价 且 收盘价 == 最高价
        df = df.with_columns([
            ((pl.col("close") >= pl.col("limit_price")) & 
             (pl.col("close") == pl.col("high"))).alias("is_limit_up")
        ])
        
        return df

    def generate_signal(
        self,
        daily_df: pl.DataFrame,
        signal_date: str
    ) -> pl.DataFrame:
        """
        生成策略信号（昨日涨停股票列表）
        
        Args:
            daily_df: 日线数据 DataFrame
            signal_date: 信号日期（YYYYMMDD，将使用 T-1 日数据）
            
        Returns:
            信号 DataFrame（包含 vt_symbol, is_limit_up, market_cap 等字段）
        """
        # 计算前一个交易日
        trade_dates = sorted(daily_df["trade_date"].unique())
        trade_dates = [str(d) for d in trade_dates]
        
        if signal_date not in trade_dates:
            raise ValueError(f"日期 {signal_date} 不在交易日历中")
        
        idx = trade_dates.index(signal_date)
        if idx == 0:
            raise ValueError("信号日期需要至少一个前序交易日")
        
        prev_date = trade_dates[idx - 1]
        
        # 筛选前一日数据
        prev_df = daily_df.filter(pl.col("trade_date") == prev_date)
        
        # 识别涨停
        prev_df = self.identify_limit_up(prev_df)
        
        # 筛选涨停股票
        limit_up_df = prev_df.filter(pl.col("is_limit_up") == True)
        
        # 读取股票基本信息（用于获取市值）
        basic_path = self.data_path / "stock_basic.parquet"
        if basic_path.exists():
            stock_basic = pl.read_parquet(basic_path)
            
            # 计算市值（使用当日收盘价 * 总股本）
            limit_up_df = limit_up_df.join(
                stock_basic.select(["ts_code", "act_shares"]),
                left_on="ts_code",
                right_on="ts_code",
                how="left"
            )
            
            limit_up_df = limit_up_df.with_columns([
                (pl.col("close") * pl.col("act_shares") * 10000).alias("market_cap")  # 市值（元）
            ])
        else:
            # 如果没有市值数据，用收盘价代替排序
            limit_up_df = limit_up_df.with_columns([
                pl.col("close").alias("market_cap")
            ])
        
        # 转换 vt_symbol 格式（vnpy 格式：ts_code 转大写）
        limit_up_df = limit_up_df.with_columns([
            pl.col("ts_code").str.to_uppercase().alias("vt_symbol")
        ])
        
        # 选择需要的字段
        signal_df = limit_up_df.select([
            "vt_symbol",
            "ts_code",
            "is_limit_up",
            "market_cap",
            "close",
            "trade_date"
        ])
        
        # 保存信号
        signal_path = self.data_path / f"signal_{signal_date}.parquet"
        signal_df.write_parquet(signal_path)
        print(f"信号已保存：{signal_path}, 涨停股票数：{len(signal_df)}")
        
        return signal_df

    def load_signal(self, signal_date: str) -> pl.DataFrame | None:
        """加载指定日期的信号"""
        signal_path = self.data_path / f"signal_{signal_date}.parquet"
        
        if not signal_path.exists():
            print(f"信号文件不存在：{signal_path}")
            return None
        
        return pl.read_parquet(signal_path)


def main():
    """示例：下载数据并生成信号"""
    # 初始化下载器
    downloader = TushareDataDownloader()
    
    # 下载股票基本信息
    downloader.download_stock_basic()
    
    # 下载日线数据（示例：最近 1 年）
    end_date = datetime.now().strftime("%Y%m%d")
    start_date = (datetime.now() - timedelta(days=365)).strftime("%Y%m%d")
    
    daily_df = downloader.download_all_daily(start_date, end_date)
    
    # 生成最新交易日的信号
    # 注意：实际使用时需要获取最新的交易日
    latest_date = str(daily_df["trade_date"].max())
    signal_df = downloader.generate_signal(daily_df, latest_date)
    
    print("\n信号数据预览:")
    print(signal_df.head(10))


if __name__ == "__main__":
    main()
