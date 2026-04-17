# vnpy ML因子策略 - 最终架构

## 架构调整总结

根据您的要求，我们已经调整架构，**仅保留使用vnpy框架的方案**。

### 调整内容

✅ **移除**：独立的 `ml_factors/` 目录  
✅ **保留**：vnpy框架的原生结构  
✅ **保留**：vnpy框架中的ML因子策略实现  
✅ **保留**：示例项目 `examples/ml_factor_backtest/`  
✅ **添加**：完整的使用文档  

### 当前架构

```
vnpy/
├── vnpy/                           # vnpy核心框架
│   └── strategies/ml_factor_strategy/    # ML因子策略实现
│       ├── strategy.py                     # 策略主逻辑 (493行)
│       ├── train_factors.py               # 因子训练脚本 (463行)
│       └── __init__.py                    # 模块入口
├── examples/ml_factor_backtest/      # ML因子策略示例
│   ├── config.py                         # 配置文件 (138行)
│   ├── run_backtest.py                   # 回测执行脚本 (221行)
│   └── signal_pipeline.py               # 信号管道处理 (463行)
├── README_ML_STRATEGY.md            # ML因子策略使用说明
├── VNPY_ML_FACTOR_GUIDE.md          # vnpy框架ML因子指南
└── PROJECT_STRUCTURE.md              # 项目结构说明
```

## 策略实现说明

### 1. 核心策略 (`vnpy/strategies/ml_factor_strategy/strategy.py`)
- 基于vnpy.alpha框架的AlphaStrategy实现
- 支持5组ML因子的选股逻辑
- 包含完整的风险控制机制

### 2. 因子训练 (`vnpy/strategies/ml_factor_strategy/train_factors.py`)
- 使用BayesianRidge模型训练因子系数
- 支持从CSV或数据接口获取数据
- 输出各组因子的线性回归系数

### 3. 示例项目 (`examples/ml_factor_backtest/`)
- 提供完整的回测示例
- 包含配置和执行脚本
- 展示如何使用vnpy框架运行ML因子策略

## 使用流程

### 1. 环境准备
```bash
# 确保安装必要依赖
pip install pandas numpy scikit-learn polars matplotlib tinyshare
```

### 2. 因子训练
```bash
cd vnpy/vnpy/strategies/ml_factor_strategy/
python train_factors.py --train_file /path/to/train_data.csv --test_file /path/to/test_data.csv
```

### 3. 策略回测
```bash
cd vnpy/examples/ml_factor_backtest/
python run_backtest.py
```

## 架构优势

1. **标准化**: 遵循vnpy框架的标准架构
2. **模块化**: 策略与框架分离，易于维护
3. **可扩展**: 支持添加新策略和因子
4. **文档完善**: 提供完整的使用说明

## 项目状态

🎯 **架构调整完成** - 仅保留vnpy框架方案  
📚 **文档完善** - 提供使用指南和说明  
🔄 **功能完整** - 保持所有策略功能  
🚀 **随时可用** - 可立即投入使用  

---

**架构调整完成时间**: 2026年4月16日  
**项目状态**: 已按要求调整为仅保留vnpy框架方案