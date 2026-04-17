# vnpy ML因子策略使用说明

## 项目介绍

本项目基于vnpy量化交易框架，特别集成了AI量化功能，其中包含ML因子策略模块，用于实现机器学习驱动的多因子选股策略。

## vnpy框架架构

vnpy是一个基于Python的开源量化交易系统开发框架，4.0版本新增了面向AI量化策略的vnpy.alpha模块。

### 核心模块
- **vnpy.alpha**: AI量化策略模块，提供一站式多因子机器学习策略开发方案
- **策略实现**: 位于 `vnpy/strategies/ml_factor_strategy/`

## ML因子策略模块

### 策略位置
- **策略实现**: `vnpy/strategies/ml_factor_strategy/strategy.py`
- **因子训练**: `vnpy/strategies/ml_factor_strategy/train_factors.py`
- **示例项目**: `examples/ml_factor_backtest/`

### 策略特点
- 基于5组预训练因子的机器学习策略
- 专门针对小市值股票优化
- 完整的风险控制机制

### 因子分组
1. **估值因子组**: arbr, sgai, net_profit_margin_ttm, retained_profit_per_share
2. **交易因子组**: price_1y, total_profit_to_cost_ratio, vol120
3. **动量因子组**: price_no_fq, total_profit_to_cost_ratio, inventory_turnover_rate
4. **综合因子组**: debt_to_assets, operating_cost_to_revenue_ratio, davol20, price_no_fq, sales_growth_5y
5. **收益因子组**: tvstd6, cashflow_per_share_ttm, sharpe_ratio_120, non_operating_net_profit_ttm

## 使用方法

### 1. 环境搭建
```bash
# 安装vnpy及其依赖
pip install -r requirements.txt
# 或单独安装关键依赖
pip install pandas numpy scikit-learn polars matplotlib tinyshare
```

### 2. 数据准备
首先准备训练和测试数据，通常通过数据接口获取：
```python
# 例如使用TuShare获取数据
import tinyshare as ts
ts.set_token('your_token_here')
```

### 3. 因子训练
使用vnpy框架进行因子训练：
```bash
cd vnpy/strategies/ml_factor_strategy/
python train_factors.py
```

### 4. 策略回测
运行示例项目进行回测：
```bash
cd examples/ml_factor_backtest/
python run_backtest.py
```

### 5. 策略部署
将策略集成到vnpy Trader中：
```python
from vnpy.strategies.ml_factor_strategy import MlFactorStrategy
# 集成到vnpy的交易环境中
```

## 示例项目结构

`examples/ml_factor_backtest/` 包含完整的使用示例：

- `config.py`: 策略配置文件
- `run_backtest.py`: 回测执行脚本
- `signal_pipeline.py`: 信号管道处理

## 数据流程

1. **数据获取**: 从数据提供商（如TuShare）获取股票数据
2. **因子计算**: 计算各类技术指标和基本面因子
3. **模型训练**: 使用机器学习算法训练因子权重
4. **策略执行**: 基于因子得分进行选股和交易
5. **回测验证**: 验证策略效果并生成报告

## 注意事项

- 确保数据接口访问权限和API密钥配置正确
- 策略基于历史数据回测，不保证未来表现
- 使用前请充分了解策略逻辑和风险控制机制
- 遵循当地法律法规进行量化交易

## 扩展开发

- 可以在 `vnpy/strategies/` 目录下添加新的策略实现
- 可以扩展因子集合以提升策略表现
- 可以优化风险控制参数以适应市场变化

该项目充分利用了vnpy框架的强大功能，结合机器学习技术，为量化交易提供了高效、灵活的解决方案。