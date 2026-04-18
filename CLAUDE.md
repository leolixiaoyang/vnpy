# VeighNa ML Factor Strategy 项目

## 项目概述

基于 **VeighNa 4.3.0** 量化交易框架的 **AI 多因子策略** 二次开发项目，核心是 ML 预训练的小市值选股策略，面向 **A 股市场**。

## 核心架构

```
Tushare/JoinQuant 数据 → 因子计算(signal_pipeline) → BayesianRidge 模型训练(train_factors)
    → 因子系数 → MlFactorStrategy 线性打分选股 → 周频调仓回测
```

## 关键文件索引

### 策略核心
- `vnpy/strategies/ml_factor_strategy/strategy.py` — **ML 因子选股策略**（打分、过滤、调仓、涨停监控）
- `vnpy/strategies/ml_factor_strategy/train_factors.py` — **BayesianRidge 因子预训练脚本**
- `vnpy/strategies/ml_factor_strategy/__init__.py` — 模块入口

### 回测执行
- `examples/ml_factor_backtest/config.py` — **回测配置**（股票池、参数、手续费）
- `examples/ml_factor_backtest/signal_pipeline.py` — **因子计算管线**（Tushare 拉数据 → 生成 signal_df）
- `examples/ml_factor_backtest/run_backtest.py` — **回测主入口**

### Alpha 框架
- `vnpy/alpha/strategy/template.py` — AlphaStrategy 基类
- `vnpy/alpha/strategy/backtesting.py` — 回测引擎
- `vnpy/alpha/model/models/bayesian_ridge_model.py` — BayesianRidge 模型实现
- `vnpy/alpha/dataset/datasets/alpha_158.py` — Alpha158 因子集（微软 Qlib）

### 其他策略
- `vnpy/strategies/limit_up_strategy/` — 涨停板策略
- `vnpy/strategies/ma5_strategy/` — MA5 策略
- `vnpy/strategies/small_cap_strategy/` — 小市值策略
- `vnpy/strategies/lingxiao_slv_strategy/` — 凌霄策略

## ML 因子策略要点

### 五组因子（17个）
| 组别 | 因子 | 数量 |
|------|------|------|
| Group1 | arbr, sgai, net_profit_margin_ttm, retained_profit_per_share | 4 |
| Group2 | price_1y, total_profit_to_cost_ratio, vol120 | 3 |
| Group3 | price_no_fq, total_profit_to_cost_ratio, inventory_turnover_rate | 3 |
| Group4 | debt_to_assets, operating_cost_to_revenue_ratio, davol20, price_no_fq, sales_growth_5y | 5 |
| Group5 | tvstd6, cashflow_per_share_ttm, sharpe_ratio_120, non_operating_net_profit_ttm | 4 |

### 选股逻辑
1. 基础过滤：排除科创板/创业板/北交所/ST/停牌/次新/涨跌停
2. 5 组因子分别线性打分，每组取前 10%
3. 前 10% 中 EPS>0，选流通市值最小 1 只
4. 每组 1 只 → 最多 5 只等权分配

### 交易规则
- **调仓**：每周一
- **空仓期**：每年 4/5 ~ 4/30
- **涨停监控**：昨日涨停股，今日涨停打开则卖出
- **下单价格**：close × (1 ± 0.05)
- **现金使用**：95%
- **最小交易量**：100 股

### 股票池
- **动态模式**（当前）：中证1000成分股（000852.SH），通过 Tushare `pro.index_weight()` 获取
- **静态模式**：12 只固定股票（平安银行、万科A、贵州茅台等）
- 配置位置：`examples/ml_factor_backtest/config.py` 的 `STOCK_POOL_MODE`

## 数据源
- **Tushare Pro**：日线、基本面、财报四表（signal_pipeline 使用）
- **JoinQuant**：因子值直接获取 + 训练标签（train_factors 使用，需 JQ 环境）

## 运行方式
```bash
# 回测
cd examples/ml_factor_backtest && python run_backtest.py

# 训练因子
cd vnpy/strategies/ml_factor_strategy && python train_factors.py --train_file train.csv --test_file test.csv
```

## 技术栈
Python, Polars, scikit-learn (BayesianRidge), Tushare, Matplotlib, VeighNa Alpha 框架
