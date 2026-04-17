# vnpy框架ML因子策略使用指南

## 项目概述

这是基于vnpy框架的机器学习多因子量化投资策略，专门针对小市值股票进行投资策略研究。

## 项目结构

```
vnpy/
├── vnpy/                           # vnpy核心框架
│   └── strategies/ml_factor_strategy/    # ML因子策略实现
│       ├── strategy.py                     # 策略主逻辑
│       ├── train_factors.py               # 因子训练脚本
│       └── __init__.py                    # 模块入口
├── examples/ml_factor_backtest/      # ML因子策略示例
│   ├── config.py                         # 配置文件
│   ├── run_backtest.py                   # 回测执行脚本
│   ├── signal_pipeline.py               # 信号管道处理
│   └── __pycache__/                     # 缓存目录
├── train_model_*.py                 # 训练脚本 (根目录)
├── run_backtest.py                  # 主回测脚本 (根目录)
├── 补充*.py                         # 因子补充脚本 (根目录)
└── *.csv                            # 数据文件 (训练/测试数据等)
```

## 使用步骤

### 1. 环境准备

确保安装必要的依赖库：
```bash
pip install -r requirements.txt
# 或者安装关键依赖
pip install pandas numpy scikit-learn polars matplotlib tinyshare tqdm
```

### 2. 数据准备

运行训练脚本来准备数据：
```bash
python train_model_efficient.py
```

补充因子数据：
```bash
python 补充因子.py
python 补充income因子.py
python 完整补充因子.py
```

### 3. 因子训练

使用vnpy框架训练因子系数：
```bash
cd vnpy/strategies/ml_factor_strategy/
python train_factors.py --train_file ../../train_data_final.csv --test_file ../../test_data_final.csv --output coefficients.json
```

### 4. 策略回测

#### 方法1: 使用示例项目
```bash
cd examples/ml_factor_backtest/
python run_backtest.py
```

#### 方法2: 使用vnpy框架
```bash
# 在适当位置导入并使用策略
from vnpy.strategies.ml_factor_strategy import MlFactorStrategy
```

## 核心功能

### 1. ML因子策略
- 基于5组预训练因子的机器学习策略
- 每组因子有对应的线性回归系数
- 对因子进行加权打分，选取最优股票

### 2. 小市值股票池
- 基本面过滤：PE、PB、ROE、净利润等
- 技术面过滤：波动率、价格趋势等
- 专门针对小市值股票进行优化

### 3. 风险控制
- 每周一调仓
- 4月5日-4月30日空仓期
- 涨停股监控和过滤
- 多种止损止盈机制

## 因子分组

1. **估值因子组**: arbr, sgai, net_profit_margin_ttm, retained_profit_per_share
2. **交易因子组**: price_1y, total_profit_to_cost_ratio, vol120
3. **动量因子组**: price_no_fq, total_profit_to_cost_ratio, inventory_turnover_rate
4. **综合因子组**: debt_to_assets, operating_cost_to_revenue_ratio, davol20, price_no_fq, sales_growth_5y
5. **收益因子组**: tvstd6, cashflow_per_share_ttm, sharpe_ratio_120, non_operating_net_profit_ttm

## 与vnpy框架的集成

- `vnpy/strategies/ml_factor_strategy/strategy.py` 实现了完整的AlphaStrategy接口
- 使用vnpy的事件驱动架构
- 与vnpy的回测引擎和实盘交易引擎完全兼容
- 可以在vnpy Trader中直接使用

## 注意事项

- 确保在使用前准备好训练和测试数据
- 检查Tushare API token配置
- 根据需要调整策略参数
- 策略基于历史数据回测，不保证未来表现