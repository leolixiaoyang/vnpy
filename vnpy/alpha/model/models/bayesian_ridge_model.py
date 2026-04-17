"""
贝叶斯岭回归模型（用于 ML 因子预训练）
=====================================
基于 JoinQuant 平台的 ML 因子小市值策略思路移植。
使用 BayesianRidge 回归对每组因子进行训练，得到因子系数。

训练逻辑：
- 将因子分为 5 组
- 每组因子独立训练
- 标签为下一期收益率
- 训练结果为因子系数，用于策略选股打分
"""

import numpy as np
import polars as pl
from sklearn.linear_model import BayesianRidge  # type: ignore

from vnpy.alpha import (
    AlphaDataset,
    AlphaModel,
    Segment,
    logger
)


class BayesianRidgeModel(AlphaModel):
    """贝叶斯岭回归模型"""

    def __init__(
        self,
        alpha_1: float = 1e-6,
        alpha_2: float = 1e-6,
        lambda_1: float = 1e-6,
        lambda_2: float = 1e-6,
        compute_score: bool = False,
        fit_intercept: bool = False,
    ) -> None:
        """
        Parameters
        ----------
        alpha_1 : float
            超参数 alpha 的 Gamma 分布先验参数
        alpha_2 : float
            超参数 alpha 的 Gamma 分布先验参数
        lambda_1 : float
            超参数 lambda 的 Gamma 分布先验参数
        lambda_2 : float
            超参数 lambda 的 Gamma 分布先验参数
        compute_score : bool
            是否计算边缘对数似然
        fit_intercept : bool
            是否拟合截距
        """
        self.alpha_1: float = alpha_1
        self.alpha_2: float = alpha_2
        self.lambda_1: float = lambda_1
        self.lambda_2: float = lambda_2
        self.compute_score: bool = compute_score
        self.fit_intercept: bool = fit_intercept

        self.model: BayesianRidge = None
        self.feature_names: list[str] = []
        self.coefficients: np.ndarray = None

    def fit(self, dataset: AlphaDataset) -> None:
        """
        训练模型

        Parameters
        ----------
        dataset : AlphaDataset
            训练数据集
        """
        # 获取训练数据
        df_train: pl.DataFrame = dataset.fetch_learn(Segment.TRAIN)
        df_valid: pl.DataFrame = dataset.fetch_learn(Segment.VALID)

        # 合并数据，去重并排序
        df_train = pl.concat([df_train, df_valid])
        df_train = df_train.unique(subset=["datetime", "vt_symbol"])
        df_train = df_train.sort(["datetime", "vt_symbol"])

        # 提取特征名称（datetime, vt_symbol 后，label 前）
        self.feature_names = df_train.columns[2:-1]

        # 处理缺失值：按日期分组填充中位数
        df_filled = df_train.clone()
        for col in self.feature_names:
            df_filled = df_filled.with_columns(
                pl.col(col).fill_null(
                    pl.col(col).median().over("datetime")
                )
            )
        df_filled = df_filled.drop_nulls(subset=self.feature_names + ["label"])

        # 转换为 numpy 数组
        X: np.ndarray = df_filled.select(self.feature_names).to_numpy()
        y: np.ndarray = np.array(df_filled["label"])

        # 创建并训练模型
        self.model = BayesianRidge(
            alpha_1=self.alpha_1,
            alpha_2=self.alpha_2,
            lambda_1=self.lambda_1,
            lambda_2=self.lambda_2,
            compute_score=self.compute_score,
            fit_intercept=self.fit_intercept,
            copy_X=False
        )
        self.model.fit(X, y)

        # 保存系数
        self.coefficients = self.model.coef_

    def predict(self, dataset: AlphaDataset, segment: Segment) -> np.ndarray:
        """
        预测

        Parameters
        ----------
        dataset : AlphaDataset
            数据集
        segment : Segment
            数据段

        Returns
        -------
        np.ndarray
            预测结果
        """
        if self.model is None:
            raise ValueError("模型尚未训练！")

        # 获取预测数据
        df: pl.DataFrame = dataset.fetch_infer(segment)
        df = df.sort(["datetime", "vt_symbol"])

        # 处理缺失值
        df_filled = df.clone()
        for col in self.feature_names:
            if col in df_filled.columns:
                df_filled = df_filled.with_columns(
                    pl.col(col).fill_null(
                        pl.col(col).median().over("datetime")
                    )
                )

        # 转换为 numpy 数组
        data: np.ndarray = df_filled.select(self.feature_names).to_numpy()

        # 返回预测结果
        result: np.ndarray = self.model.predict(data)

        return result

    def detail(self) -> dict:
        """
        输出模型详细信息

        Returns
        -------
        dict
            模型系数和特征信息
        """
        if self.model is None:
            logger.info("模型尚未训练！")
            return {}

        # 特征系数
        coef: np.ndarray = self.model.coef_

        # 组合特征名称和系数
        data: list[tuple[str, float]] = list(zip(self.feature_names, coef))

        # 按绝对值排序
        data.sort(key=lambda x: abs(x[1]), reverse=True)

        # 打印特征重要性
        logger.info(f"贝叶斯岭回归模型特征总数量: {len(data)}")
        logger.info(f"因子系数:")
        for name, importance in data:
            logger.info(f"  {name}: {importance:.10e}")

        # 返回系数字典
        return {
            "feature_names": self.feature_names,
            "coefficients": list(coef),
            "coef_dict": {name: coef for name, coef in data}
        }

    def get_coefficients(self) -> list[float]:
        """
        获取因子系数列表

        Returns
        -------
        list[float]
            因子系数
        """
        if self.coefficients is None:
            raise ValueError("模型尚未训练！")
        return list(self.coefficients)


class MlFactorGroupModel:
    """
    ML 因子分组训练模型
    ==================
    对 5 组因子分别进行 BayesianRidge 训练，得到各组系数。

    因子分组：
    - Group 1: ARBR, SGAI, net_profit_margin_ttm, retained_profit_per_share
    - Group 2: price_1y, total_profit_to_cost_ratio, vol120
    - Group 3: price_no_fq, total_profit_to_cost_ratio, inventory_turnover_rate
    - Group 4: debt_to_assets, operating_cost_to_revenue_ratio, davol20, price_no_fq, sales_growth_5y
    - Group 5: tvstd6, cashflow_per_share_ttm, sharpe_ratio_120, non_operating_net_profit_ttm
    """

    # 因子分组配置（列名映射到 JoinQuant 因子名）
    FACTOR_GROUPS: dict[str, dict] = {
        "group1": {
            "factors": ["arbr", "sgai", "net_profit_margin_ttm", "retained_profit_per_share"],
            "jq_names": ["ARBR", "SGAI", "net_profit_to_total_operate_revenue_ttm", "retained_profit_per_share"],
        },
        "group2": {
            "factors": ["price_1y", "total_profit_to_cost_ratio", "vol120"],
            "jq_names": ["Price1Y", "total_profit_to_cost_ratio", "VOL120"],
        },
        "group3": {
            "factors": ["price_no_fq", "total_profit_to_cost_ratio", "inventory_turnover_rate"],
            "jq_names": ["price_no_fq", "total_profit_to_cost_ratio", "inventory_turnover_rate"],
        },
        "group4": {
            "factors": ["debt_to_assets", "operating_cost_to_revenue_ratio", "davol20", "price_no_fq", "sales_growth_5y"],
            "jq_names": ["debt_to_assets", "operating_cost_to_operating_revenue_ratio", "DAVOL20", "price_no_fq", "sales_growth"],
        },
        "group5": {
            "factors": ["tvstd6", "cashflow_per_share_ttm", "sharpe_ratio_120", "non_operating_net_profit_ttm"],
            "jq_names": ["TVSTD6", "cashflow_per_share_ttm", "sharpe_ratio_120", "non_operating_net_profit_ttm"],
        },
    }

    def __init__(self) -> None:
        """初始化"""
        self.models: dict[str, BayesianRidgeModel] = {}
        self.coefficients: dict[str, list[float]] = {}

    def fit_groups(self, dataset: AlphaDataset) -> None:
        """
        训练所有因子分组

        Parameters
        ----------
        dataset : AlphaDataset
            训练数据集，需包含所有因子列和 label 列
        """
        for group_name, group_config in self.FACTOR_GROUPS.items():
            logger.info(f"开始训练 {group_name}...")

            # 创建单组数据集
            group_dataset = self._create_group_dataset(dataset, group_config["factors"])

            # 创建并训练模型
            model = BayesianRidgeModel(fit_intercept=False)
            model.fit(group_dataset)

            # 保存模型和系数
            self.models[group_name] = model
            self.coefficients[group_name] = model.get_coefficients()

            # 输出系数
            logger.info(f"{group_name} 训练完成，系数: {self.coefficients[group_name]}")

    def _create_group_dataset(
        self,
        dataset: AlphaDataset,
        factor_cols: list[str]
    ) -> "GroupDataset":
        """
        创建单组因子数据集

        Parameters
        ----------
        dataset : AlphaDataset
            原数据集
        factor_cols : list[str]
            该组因子列名

        Returns
        -------
        GroupDataset
            单组因子数据集
        """
        return GroupDataset(dataset, factor_cols)

    def get_all_coefficients(self) -> dict[str, list[float]]:
        """
        获取所有分组的因子系数

        Returns
        -------
        dict[str, list[float]]
            各组因子系数
        """
        return self.coefficients

    def detail(self) -> None:
        """
        输出所有模型的详细信息
        """
        for group_name, model in self.models.items():
            logger.info(f"\n{'='*50}")
            logger.info(f"{group_name} 因子系数:")
            model.detail()


class GroupDataset:
    """
    单组因子数据集包装类
    """

    def __init__(self, dataset: AlphaDataset, factor_cols: list[str]) -> None:
        """
        Parameters
        ----------
        dataset : AlphaDataset
            原数据集
        factor_cols : list[str]
            该组因子列名
        """
        self.dataset = dataset
        self.factor_cols = factor_cols

    def fetch_learn(self, segment: Segment) -> pl.DataFrame:
        """
        获取学习数据（只包含该组因子）
        """
        df = self.dataset.fetch_learn(segment)
        select_cols = ["datetime", "vt_symbol"] + self.factor_cols + ["label"]
        available_cols = [col for col in select_cols if col in df.columns]
        return df.select(available_cols)

    def fetch_infer(self, segment: Segment) -> pl.DataFrame:
        """
        获取推理数据（只包含该组因子）
        """
        df = self.dataset.fetch_infer(segment)
        select_cols = ["datetime", "vt_symbol"] + self.factor_cols
        available_cols = [col for col in select_cols if col in df.columns]
        return df.select(available_cols)
