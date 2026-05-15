# Tinyshare 全天候轮动（精简版）

当前分支已按“激进清理”原则，收敛为一个可独立运行的 tinyshare 策略项目。

## 保留内容

- `examples/all_weather_rotation_backtest/`：策略实现、数据访问、回测入口
- `docs/new_strategy_stratch.py`：JoinQuant 原策略参考
- `tests/`：单元测试与连通性测试

## 快速开始

```bash
pip install -e .[test]
cd examples/all_weather_rotation_backtest
python run_backtest.py
```

## 运行测试

```bash
pytest
```

如需执行真实接口连通性测试（会请求 tinyshare/Tushare）：

```bash
$env:RUN_LIVE_TINYSHARE_TESTS="1"
pytest -k live_tinyshare
```
