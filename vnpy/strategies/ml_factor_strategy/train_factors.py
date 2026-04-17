"""
ML 因子预训练脚本
================
使用 vnpy alpha 模块的 BayesianRidge 模型对因子进行训练。

训练流程：
1. 准备数据：获取小市值股票池 + 因子数据 + 收益率标签
2. 创建数据集：使用 AlphaDataset
3. 分组训练：对 5 组因子分别训练
4. 输出系数：保存到策略配置或 JSON 文件

使用方法：
    python train_factors.py --start 2009-01-01 --end 2024-01-01 --output coefficients.json

数据来源：
    - JoinQuant 平台（需要 jqdata 库）
    - 或本地 CSV 数据
"""

import argparse
import json
from datetime import datetime
from pathlib import Path

import polars as pl
import pandas as pd
from tqdm import tqdm

from vnpy.alpha import AlphaDataset, Segment, logger
from vnpy.alpha.model.models.bayesian_ridge_model import BayesianRidgeModel, MlFactorGroupModel


# 因子分组配置
FACTOR_GROUPS: dict[str, dict] = {
    "group1": {
        "factors": ["arbr", "sgai", "net_profit_margin_ttm", "retained_profit_per_share"],
    },
    "group2": {
        "factors": ["price_1y", "total_profit_to_cost_ratio", "vol120"],
    },
    "group3": {
        "factors": ["price_no_fq", "total_profit_to_cost_ratio", "inventory_turnover_rate"],
    },
    "group4": {
        "factors": ["debt_to_assets", "operating_cost_to_revenue_ratio", "davol20", "price_no_fq", "sales_growth_5y"],
    },
    "group5": {
        "factors": ["tvstd6", "cashflow_per_share_ttm", "sharpe_ratio_120", "non_operating_net_profit_ttm"],
    },
}

# 所有因子列表
ALL_FACTORS: list[str] = [
    "arbr", "sgai", "net_profit_margin_ttm", "retained_profit_per_share",
    "price_1y", "total_profit_to_cost_ratio", "vol120",
    "price_no_fq", "inventory_turnover_rate",
    "debt_to_assets", "operating_cost_to_revenue_ratio", "davol20", "sales_growth_5y",
    "tvstd6", "cashflow_per_share_ttm", "sharpe_ratio_120", "non_operating_net_profit_ttm",
]


def prepare_data_from_csv(
    train_file: str,
    test_file: str,
) -> pl.DataFrame:
    """
    从 CSV 文件准备数据

    Parameters
    ----------
    train_file : str
        训练数据 CSV 文件路径
    test_file : str
        测试数据 CSV 文件路径

    Returns
    -------
    pl.DataFrame
        合并后的数据
    """
    # 读取 CSV
    train_df = pl.read_csv(train_file)
    test_df = pl.read_csv(test_file)

    # 合并
    df = pl.concat([train_df, test_df])

    # 重命名列（如果需要）
    column_mapping = {
        "net_profit_to_total_operate_revenue_ttm": "net_profit_margin_ttm",
        "operating_cost_to_operating_revenue_ratio": "operating_cost_to_revenue_ratio",
        "sales_growth": "sales_growth_5y",
        "VOL120": "vol120",
        "DAVOL20": "davol20",
        "TVSTD6": "tvstd6",
        "ARBR": "arbr",
        "SGAI": "sgai",
        "Price1Y": "price_1y",
    }

    for old_name, new_name in column_mapping.items():
        if old_name in df.columns:
            df = df.rename({old_name: new_name})

    # 确保 datetime 列格式正确
    if "date" in df.columns:
        df = df.rename({"date": "datetime"})
    
    # 转换 datetime 格式
    df = df.with_columns(
        pl.col("datetime").str.to_datetime("%Y-%m-%d")
    )

    # 确保有 vt_symbol 列
    if "code" in df.columns:
        df = df.rename({"code": "vt_symbol"})
    if "id" in df.columns and "vt_symbol" not in df.columns:
        df = df.rename({"id": "vt_symbol"})

    # 确保 pchg 列存在并重命名为 label
    if "pchg" in df.columns:
        df = df.rename({"pchg": "label"})

    return df


def prepare_data_from_jq(
    start_date: str,
    end_date: str,
    stock_pool: str = "small_25",
    period: str = "W",
) -> pl.DataFrame:
    """
    从 JoinQuant 平台获取数据（需要在 JQ 平台运行）

    Parameters
    ----------
    start_date : str
        开始日期
    end_date : str
        结束日期
    stock_pool : str
        股票池类型
    period : str
        调仓周期

    Returns
    -------
    pl.DataFrame
        因子数据
    """
    try:
        import jqdata as jq
        from jqdata import get_price, get_index_stocks, get_extras, get_security_info, get_fundamentals, valuation
        from jqfactor import get_factor_values
    except ImportError:
        logger.error("需要安装 jqdata 库，请在 JoinQuant 平台运行")
        raise

    # JoinQuant 因子列表
    jq_factors = [
        'Price1Y', 
        'total_profit_to_cost_ratio', 
        'VOL120',
        'ARBR', 
        'SGAI', 
        'net_profit_to_total_operate_revenue_ttm', 
        'retained_profit_per_share',
        'price_no_fq', 
        'inventory_turnover_rate',
        'debt_to_assets', 
        'operating_cost_to_operating_revenue_ratio', 
        'DAVOL20', 
        'sales_growth',
        'TVSTD6', 
        'cashflow_per_share_ttm', 
        'sharpe_ratio_120', 
        'non_operating_net_profit_ttm'
    ]

    # 获取日期列表
    def get_period_date(period, start_date, end_date):
        stock_data = get_price('000001.XSHE', start_date, end_date, 'daily', fields=['close'])
        stock_data['date'] = stock_data.index
        period_stock_data = stock_data.resample(period).last()
        period_stock_data = period_stock_data.set_index('date').dropna()
        date = period_stock_data.index
        pydate_array = date.to_pydatetime()
        date_only_array = np.vectorize(lambda s: s.strftime('%Y-%m-%d'))(pydate_array)
        date_list = list(date_only_array)
        start_date_dt = datetime.strptime(start_date, "%Y-%m-%d")
        start_date_dt = start_date_dt - datetime.timedelta(days=1)
        date_list.insert(0, start_date_dt.strftime("%Y-%m-%d"))
        return date_list

    date_list = get_period_date(period, start_date, end_date)

    # 获取股票池
    def get_stock(stockPool, begin_date):
        if stockPool == 'small_25':
            initial_list = get_index_stocks('000002.XSHG', begin_date) + get_index_stocks('399107.XSHE', begin_date)
            stockList = list(get_fundamentals(
                query(valuation.code, valuation.market_cap).filter(
                    valuation.code.in_(initial_list),
                    valuation.market_cap < 25
                ).order_by(
                    valuation.circulating_market_cap.asc()
                )).code)[:50]
        
        # 剔除 ST
        st_data = get_extras('is_st', stockList, count=1, end_date=begin_date)
        stockList = [stock for stock in stockList if not st_data[stock][0]]
        return stockList

    # 收集数据
    all_data = []
    for date in tqdm(date_list[:-1]):
        try:
            next_date = date_list[date_list.index(date) + 1]
            stockList = get_stock(stock_pool, date)
            
            # 获取因子数据
            factor_data = get_factor_values(
                securities=stockList,
                factors=jq_factors,
                count=1,
                end_date=date
            )
            
            # 构建 DataFrame
            row_data = {}
            for factor_name, factor_df in factor_data.items():
                row_data[factor_name] = factor_df.iloc[0]
            
            # 获取收益率
            close_data = get_price(stockList, date, next_date, '1d', 'close')['close']
            returns = close_data.iloc[-1] / close_data.iloc[1] - 1
            
            # 构建单日数据
            for stock in stockList:
                row = {
                    'datetime': date,
                    'vt_symbol': stock,
                    'label': returns.get(stock, 0),
                }
                for factor_name, factor_series in row_data.items():
                    row[factor_name] = factor_series.get(stock, None)
                all_data.append(row)
        except Exception as e:
            logger.warning(f"获取 {date} 数据失败: {e}")
            continue

    # 转换为 Polars DataFrame
    df = pl.DataFrame(all_data)
    
    return df


def train_factor_coefficients(
    df: pl.DataFrame,
    train_period: tuple[str, str],
    valid_period: tuple[str, str],
    test_period: tuple[str, str],
) -> dict[str, list[float]]:
    """
    训练因子系数

    Parameters
    ----------
    df : pl.DataFrame
        数据集
    train_period : tuple[str, str]
        训练期间
    valid_period : tuple[str, str]
        验证期间
    test_period : tuple[str, str]
        测试期间

    Returns
    -------
    dict[str, list[float]]
        各组因子系数
    """
    # 创建数据集
    dataset = AlphaDataset(
        df=df,
        train_period=train_period,
        valid_period=valid_period,
        test_period=test_period,
    )

    # 训练各组因子
    coefficients = {}
    
    for group_name, group_config in FACTOR_GROUPS.items():
        logger.info(f"\n{'='*50}")
        logger.info(f"开始训练 {group_name}...")
        
        factor_cols = group_config["factors"]
        
        # 检查因子列是否存在
        missing_factors = [f for f in factor_cols if f not in df.columns]
        if missing_factors:
            logger.warning(f"{group_name} 缺少因子: {missing_factors}")
            continue
        
        # 创建单组数据
        group_dataset = GroupDatasetWrapper(dataset, factor_cols)
        
        # 训练模型
        model = BayesianRidgeModel(fit_intercept=False)
        model.fit(group_dataset)
        
        # 获取系数
        coef = model.get_coefficients()
        coefficients[group_name] = coef
        
        logger.info(f"{group_name} 训练完成")
        logger.info(f"因子: {factor_cols}")
        logger.info(f"系数: {coef}")
        
        # 输出模型详情
        model.detail()

    return coefficients


class GroupDatasetWrapper:
    """
    单组因子数据集包装类
    """

    def __init__(self, dataset: AlphaDataset, factor_cols: list[str]) -> None:
        self.dataset = dataset
        self.factor_cols = factor_cols

    def fetch_learn(self, segment: Segment) -> pl.DataFrame:
        df = self.dataset.fetch_learn(segment)
        select_cols = ["datetime", "vt_symbol"] + self.factor_cols + ["label"]
        available_cols = [col for col in select_cols if col in df.columns]
        return df.select(available_cols)

    def fetch_infer(self, segment: Segment) -> pl.DataFrame:
        df = self.dataset.fetch_infer(segment)
        select_cols = ["datetime", "vt_symbol"] + self.factor_cols
        available_cols = [col for col in select_cols if col in df.columns]
        return df.select(available_cols)


def save_coefficients(
    coefficients: dict[str, list[float]],
    output_file: str,
) -> None:
    """
    保存系数到 JSON 文件

    Parameters
    ----------
    coefficients : dict[str, list[float]]
        因子系数
    output_file : str
        输出文件路径
    """
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(coefficients, f, indent=2, ensure_ascii=False)
    
    logger.info(f"系数已保存到: {output_file}")


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="ML 因子预训练")
    parser.add_argument('--train_file', type=str, help='训练数据 CSV 文件')
    parser.add_argument('--test_file', type=str, help='测试数据 CSV 文件')
    parser.add_argument('--start', type=str, default='2009-01-01', help='开始日期')
    parser.add_argument('--end', type=str, default='2024-01-01', help='结束日期')
    parser.add_argument('--train_ratio', type=float, default=0.8, help='训练集比例')
    parser.add_argument('--output', type=str, default='coefficients.json', help='输出文件')
    
    args = parser.parse_args()

    logger.info("ML 因子预训练开始")

    # 准备数据
    if args.train_file and args.test_file:
        logger.info("从 CSV 文件读取数据...")
        df = prepare_data_from_csv(args.train_file, args.test_file)
    else:
        logger.info("从 JoinQuant 平台获取数据...")
        df = prepare_data_from_jq(args.start, args.end)

    logger.info(f"数据总量: {len(df)} 条")

    # 计算训练/验证/测试期间
    dates = df["datetime"].unique().sort()
    total_dates = len(dates)
    
    train_end_idx = int(total_dates * args.train_ratio * 0.9)
    valid_end_idx = int(total_dates * args.train_ratio)
    
    train_period = (str(dates[0]), str(dates[train_end_idx]))
    valid_period = (str(dates[train_end_idx + 1]), str(dates[valid_end_idx]))
    test_period = (str(dates[valid_end_idx + 1]), str(dates[-1]))

    logger.info(f"训练期间: {train_period}")
    logger.info(f"验证期间: {valid_period}")
    logger.info(f"测试期间: {test_period}")

    # 训练因子系数
    coefficients = train_factor_coefficients(df, train_period, valid_period, test_period)

    # 保存系数
    save_coefficients(coefficients, args.output)

    # 输出用于策略的代码片段
    logger.info("\n" + "="*50)
    logger.info("策略参数配置:")
    for group_name, coef in coefficients.items():
        logger.info(f"{group_name}_coeffs = {coef}")

    logger.info("ML 因子预训练完成")


if __name__ == "__main__":
    main()
