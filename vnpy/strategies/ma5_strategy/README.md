# MA5 突破策略

## 📖 策略说明

基于 5 日均线的突破策略，适用于趋势明显的股票。

## 🎯 策略逻辑

### 买入条件（同时满足）
1. 收盘价向上突破 MA5
2. 前一日收盘价 ≤ 前一日 MA5
3. 突破确认：收盘价 > MA5 × 1.01（超过 1%）
4. 成交量确认：当日成交量 > 5 日均量

### 卖出条件（满足任一）
1. 收盘价向下突破 MA5
2. 固定止损：亏损 ≥ -10%

### 仓位管理
- 全仓买入单只股票
- 保留 1% 现金用于手续费

## ⚙️ 策略参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `breakout_threshold` | 0.01 | 突破确认阈值（1%） |
| `stop_loss_rate` | 0.10 | 固定止损（10%） |
| `volume_ratio` | 1.0 | 成交量倍数 |
| `max_positions` | 1 | 最大持仓数 |
| `price_add` | 0.05 | 下单价格调整（5%） |

## 🚀 使用方法

### 1. 导入策略

```python
from vnpy.strategies.ma5_strategy import MA5BreakoutStrategy
```

### 2. 配置参数

```python
setting = {
    "breakout_threshold": 0.01,
    "stop_loss_rate": 0.10,
    "volume_ratio": 1.5,  # 修改成交量确认倍数
}
```

### 3. 添加到回测引擎

```python
from vnpy.alpha.strategy import BacktestingEngine

engine = BacktestingEngine(lab)
engine.add_strategy(MA5BreakoutStrategy, setting, signal_df)
```

## 📊 回测结果（金风科技 2023-2025）

| 指标 | 值 |
|------|-----|
| 总收益率 | 20.37% |
| 年化收益率 | ~6.8% |
| 交易次数 | 26 次 |
| 胜率 | 23.08% |
| 最大回撤 | 5.45% |

## ⚠️ 注意事项

1. **胜率低**：约 23%，但盈亏比高（约 3.4:1）
2. **适合趋势股**：震荡市可能频繁止损
3. **需要放量**：成交量确认过滤假突破

## 📚 相关文件

- `strategy.py` - 策略类实现
- `examples/ma5_backtest/run_backtest.py` - 回测脚本
- `examples/ma5_backtest/config.py` - 配置文件

## 📝 版本

- **版本**: 1.0
- **日期**: 2026-03-31
- **作者**: Shawn
