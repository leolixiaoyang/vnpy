# 全天候轮动（tinyshare 复刻版）

该目录实现了对 [docs/new_strategy_stratch.py](../../docs/new_strategy_stratch.py) 的 tinyshare 版本复刻：

- 月初调仓（大小盘强弱切换）
- 昨日涨停次日开板卖出
- 持仓 -8% 止损
- 卖出后补仓跌幅最大的持仓标的
- 外盘 ETF 兜底模式

## 运行前准备

1. 安装依赖（确保已安装 tinyshare）：

```bash
pip install tinyshare pandas pyarrow
```

2. 设置 token：

```bash
# PowerShell
$env:TUSHARE_TOKEN="你的token"
```

## 运行

```bash
cd examples/all_weather_rotation_backtest
python run_backtest.py
```

输出文件：

- `data/tushare/all_weather_rotation/results/all_weather_trades.csv`
- `data/tushare/all_weather_rotation/results/all_weather_equity.csv`
- `data/tushare/all_weather_rotation/results/all_weather_summary.csv`

## 说明

- 与 JoinQuant 版本相比，部分字段和筛选在 tinyshare 中存在接口差异，已使用最接近的财务字段进行映射。
- `index_weight` 在权限不足时会退化使用配置中的兜底股票池。
- 全部行情和财务请求默认缓存到 `data/tushare/all_weather_rotation`。
