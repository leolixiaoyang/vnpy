# Alpha 策略调试总结

## 📊 测试进展

### ✅ 已完成

| 项目 | 状态 | 说明 |
|------|------|------|
| vnpy 安装 | ✅ | 4.3.0 版本 |
| AlphaLab 创建 | ✅ | 可正常创建和使用 |
| BarData 保存 | ✅ | 可保存 K 线数据到 lab |
| 合约配置 | ✅ | 可配置手续费等参数 |
| BacktestingEngine 初始化 | ✅ | 可创建回测引擎 |
| set_parameters | ✅ | 参数设置正常 |
| add_strategy | ✅ | 策略添加成功 |
| run_backtesting | ✅ | 回测运行完成 |
| 策略初始化 | ✅ | `on_init()` 被调用 |

### ❌ 问题

| 问题 | 现象 | 可能原因 |
|------|------|----------|
| `on_bars()` 未调用 | 没有看到策略日志 | 数据加载或回放逻辑问题 |
| 没有交易产生 | `trade_count = 0` | 策略逻辑未执行 |
| `daily_df` 属性缺失 | `'BacktestingEngine' object has no attribute 'daily_df'` | 结果计算需要每日数据 |

---

## 🔍 根本原因分析

### 1. on_bars() 未被调用

**可能原因**：
- `load_data()` 没有正确加载 K 线数据
- `history_data` 为空
- 回测引擎的数据回放逻辑有问题

**验证方法**：
```python
# 在 run_backtesting() 后添加
print(f"历史数据条数：{len(engine.history_data)}")
print(f"策略实例：{engine.strategy}")
```

### 2. 信号数据格式

vnpy Alpha 模块期望的信号格式：
```python
# 必需列
signal_df = pl.DataFrame({
    "datetime": [datetime, ...],  # 日期
    "vt_symbol": ["000001.SZ", ...],  # 股票代码
    "signal": [0.5, ...],  # 信号值（数值型）
})
```

我们的信号格式（正确）：
```python
signal_df = signal_df.select(["datetime", "vt_symbol", "signal"])
```

### 3. 官方示例对比

官方示例流程：
1. 创建 `AlphaLab`
2. 使用 `download_data_rq.ipynb` 下载数据并保存到 lab
3. 运行 research workflow 生成信号
4. 创建 `BacktestingEngine(lab)`
5. `engine.set_parameters(...)`
6. `engine.add_strategy(..., signal_df)`
7. `engine.run_backtesting()`

我们的流程基本一致，但可能缺少某些数据准备步骤。

---

## 📝 简化版回测（可用）

`simple_backtest.py` 可以正常工作：

```bash
cd examples/limit_up_strategy
python3 simple_backtest.py
```

**结果**：
- 下载 12 只股票 1 年数据
- 识别 4 次涨停
- 产生 2 次交易
- 总收益率：-3.82%

---

## 🎯 下一步建议

### 方案 A：完善 Alpha 回测（推荐用于生产）

1. **查看 vnpy 官方文档**：确认数据准备流程
2. **调试 load_data()**：打印 `history_data` 内容
3. **检查信号时间对齐**：确保信号日期与 K 线日期匹配
4. **参考官方 notebook**：完整运行一个示例

### 方案 B：使用简化版（推荐用于快速验证）

1. **扩大股票池**：测试更多股票
2. **优化策略逻辑**：增加筛选条件
3. **添加可视化**：资金曲线、收益分布
4. **导出信号文件**：可用于其他回测框架

---

## 📁 文件清单

| 文件 | 用途 | 状态 |
|------|------|------|
| `simple_backtest.py` | 简化版回测 | ✅ 可用 |
| `alpha_backtest.py` | Alpha 正式版回测 | ❌ 调试中 |
| `test_alpha_minimal.py` | 最小化测试 | ❌ 调试中 |
| `limit_up_strategy.py` | 策略类（原始版） | ✅ |
| `limit_up_alpha_strategy.py` | 策略类（Alpha 版） | ✅ |
| `data_downloader.py` | Tushare 数据下载 | ✅ |

---

## 💡 关键发现

1. **vnpy Alpha 模块复杂度高**：需要完整的数据准备流程
2. **信号格式要求严格**：必须是 `datetime`, `vt_symbol`, `signal` 三列
3. **lab 数据存储重要**：K 线数据必须通过 `lab.save_bar_data()` 保存
4. **简化版更实用**：对于策略验证，简化版已经足够

---

## 🚀 建议行动

**短期**：使用 `simple_backtest.py` 验证策略逻辑

**中期**：参考官方 notebook 完整流程，调试 Alpha 回测

**长期**：策略成熟后，使用 Alpha 引擎进行实盘交易

---

**更新时间**：2026-03-31
**作者**：Shawn
