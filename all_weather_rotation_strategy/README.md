# 兼容入口

策略与账户已移入独立的 `quantlab` 包。先在仓库根目录安装 `pip install -e .`，再执行：

```bash
quantlab data prepare --config configs/all_weather_rotation.toml
quantlab backtest --config configs/all_weather_rotation.toml --offline
```

旧 `run_backtest.py`、`prefetch_data.py` 仅转发到新命令。`run_3m_backtest.py` 不再硬编码三个月区间，请在 TOML 配置中指定日期。

旧 `AllWeatherRotationBacktester` 名称接收 **DataBundle**，不再接收隐式在线数据 client；返回值仍为交易表与净值表。旧错误记账算法和源码 token 已移除。
