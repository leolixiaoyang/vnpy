# vnpy项目结构说明

## 整体架构

本项目是基于vnpy量化交易框架的AI量化系统，重点包含ML因子策略模块。

## 目录结构

```
vnpy/
├── vnpy/                           # vnpy核心框架
│   └── strategies/                    # 策略模块
│       └── ml_factor_strategy/           # ML因子策略
│           ├── strategy.py                  # 策略实现
│           ├── train_factors.py             # 因子训练
│           └── __init__.py                  # 模块入口
├── examples/                       # 示例项目
│   └── ml_factor_backtest/             # ML因子回测示例
│       ├── config.py                       # 配置
│       ├── run_backtest.py                 # 回测执行
│       └── signal_pipeline.py              # 信号处理
├── train_model_*.py               # 数据训练脚本
├── run_backtest.py                # 主回测脚本
├── 补充*.py                      # 因子补充脚本
├── *.csv                         # 训练/测试数据文件
├── *.png                         # 回测结果图表
├── VNPY_ML_FACTOR_GUIDE.md       # ML因子策略使用指南
└── PROJECT_STRUCTURE.md           # 本项目结构说明
```

## 核心组件

### 1. vnpy框架 (vnpy/)
- 提供完整的量化交易基础设施
- 包含事件驱动引擎、数据管理、回测引擎等
- ML因子策略作为插件策略模块集成

### 2. ML因子策略 (vnpy/strategies/ml_factor_strategy/)
- 基于机器学习的多因子选股策略
- 针对小市值股票优化
- 包含完整的训练和回测流程

### 3. 示例项目 (examples/ml_factor_backtest/)
- 演示如何使用vnpy框架运行ML因子策略
- 包含配置文件和执行脚本
- 作为策略验证和测试的参考

### 4. 数据处理脚本 (根目录)
- `train_model_*.py`: 数据获取和预处理
- `run_backtest.py`: 策略回测执行
- `补充*.py`: 因子数据补充

## 使用方式

### 策略开发
- 修改 `vnpy/strategies/ml_factor_strategy/strategy.py` 进行策略逻辑调整
- 使用 `vnpy/strategies/ml_factor_strategy/train_factors.py` 训练因子系数

### 策略运行
- 执行根目录的训练脚本准备数据
- 使用 `examples/ml_factor_backtest/` 进行回测验证
- 可集成到vnpy Trader中进行实盘交易

## 项目特点

- **模块化设计**: 策略与框架分离，易于维护
- **可扩展性**: 支持添加新的因子和策略
- **完整性**: 从数据获取到策略回测的完整流程
- **实用性**: 专注于A股小市值股票的实际应用