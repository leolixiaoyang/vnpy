# ML Factor Strategy
#
# 包含：
# - MlFactorStrategy: ML 因子小市值策略
# - train_factors: 因子预训练脚本
#
# 使用方法：
# 1. 运行预训练脚本生成因子系数
#    python train_factors.py --train_file train.csv --test_file test.csv
#
# 2. 将生成的系数配置到策略参数中
#
# 3. 运行回测或实盘交易

from .strategy import MlFactorStrategy

__all__ = ["MlFactorStrategy"]
