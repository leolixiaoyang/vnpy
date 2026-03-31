# 昨日涨停今日买入策略

## 📖 策略说明

基于 A 股市场涨停板效应的动量策略：
- **T 日**：筛选涨停股票（根据板块区分涨停幅度）
- **T+1 日**：开盘买入市值最大的前 10 只
- **持有期**：动态止盈止损，最多持有 5 天

## 📁 文件结构

```
limit_up_strategy/
├── __init__.py              # 包初始化
├── limit_up_strategy.py     # 策略主逻辑
├── data_downloader.py       # Tushare 数据下载
├── backtest_config.py       # 回测配置示例
└── README.md                # 本文件
```

## 🚀 快速开始

### 1. 配置 Tushare Token

```bash
# 方式 1：环境变量（推荐）
export TUSHARE_TOKEN=your_token_here

# 方式 2：在代码中设置
# 编辑 data_downloader.py，传入 token 参数
```

获取 Token：https://tushare.pro/user/token

### 2. 下载数据

```bash
cd /home/admin/openclaw/workspace/vnpy/strategies/limit_up_strategy
python data_downloader.py
```

数据将保存到：`/home/admin/openclaw/workspace/data/tushare/`

### 3. 运行回测

```bash
python backtest_config.py
```

## ⚙️ 策略参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `max_positions` | 10 | 最大持仓数 |
| `stop_loss_rate` | 0.05 | 止损 5% |
| `take_profit_rate` | 0.15 | 止盈 15% |
| `trailing_stop_rate` | 0.05 | 回撤止盈 5% |
| `max_hold_days` | 5 | 最多持有 5 天 |
| `min_volume` | 100 | 最小交易单位（手）|
| `price_add` | 0.01 | 下单价格调整 1% |

## 📊 涨停判定规则

| 板块 | 代码特征 | 涨停幅度 |
|------|----------|----------|
| 主板 | 000xxx, 001xxx, 002xxx, 600xxx, 601xxx, 603xxx, 605xxx | 10% |
| 科创板 | 688xxx | 20% |
| 创业板 | 300xxx | 20% |
| 北交所 | 8xxxxx, 4xxxxx, 920xxx | 30% |
| ST 股票 | 名称含 ST | 5% |

## 📈 交易逻辑

### 买入条件
1. 昨日涨停
2. 按市值从大到小排序
3. 取前 10 只
4. 开盘价买入

### 卖出条件（满足任一即卖出）
1. **止损**：亏损 ≥ 5%
2. **止盈**：盈利 ≥ 15%
3. **回撤止盈**：盈利后从最高点回撤 ≥ 5%
4. **超期**：持有 ≥ 5 天

## 🔧 自定义配置

### 修改股票池

编辑 `backtest_config.py`：

```python
engine.set_parameters(
    vt_symbols=["000001.SZ", "000002.SZ", ...],  # 自定义股票池
    ...
)
```

### 修改回测周期

```python
engine.set_parameters(
    start=datetime(2024, 1, 1),
    end=datetime(2024, 12, 31),
    ...
)
```

### 修改资金和费率

```python
engine.set_parameters(
    capital=1000000,    # 初始资金
    rate=0.0003,        # 手续费率
    slippage=0.0,       # 滑点
    ...
)
```

## 📝 注意事项

1. **数据质量**：确保 Tushare 数据完整，特别是前收盘价字段
2. **涨跌停限制**：回测中需考虑实际涨跌停无法成交的情况
3. **停牌处理**：策略会自动跳过停牌股票
4. **流动性**：建议增加成交额过滤条件（如日成交额>1 亿）
5. **滑点成本**：实盘时需考虑更大的滑点

## 📊 性能指标

回测完成后将输出：
- 年化收益率
- 夏普比率
- 最大回撤
- 胜率
- 盈亏比
- 交易次数

## 🐛 常见问题

### Q: 提示 "TUSHARE_TOKEN not found"
A: 确保已设置环境变量或在代码中传入 token

### Q: 数据下载失败
A: 检查网络连接和 token 权限，Tushare 部分数据需要积分

### Q: 回测结果为空
A: 检查数据日期范围是否覆盖回测周期

## 📚 相关文档

- [VeighNa 官方文档](https://www.vnpy.com/docs/cn/index.html)
- [Tushare API 文档](https://tushare.pro/document/2)
- [Alpha 模块文档](../../vnpy/alpha/)

## 📄 许可证

MIT
