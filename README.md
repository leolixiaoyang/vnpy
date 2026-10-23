# Quantlab：独立的轻量量化研究框架

Python 3.11+，不依赖 vnpy、聚宽、数据库服务或图形界面。核心提供数据快照、账户与成交、日线回测、策略协议和实验报告。第一个策略是聚宽全天候轮动的**日线收盘近似移植**。

## 安装与离线演示

```bash
python -m pip install -e '.[test]'
quantlab doctor --provider tinyshare
quantlab demo --output /tmp/quantlab-demo
quantlab backtest --config /tmp/quantlab-demo/demo.toml --offline
pytest
```

演示全部使用确定性的合成数据，不能作为真实收益证明。`demo.toml` 中的路径相对配置文件解析，安装后可以从任意目录运行。

默认安装不包含 tinyshare 或 tushare。tinyshare 是可选的现有 SDK 接入，当前 PyPI 隔离状态下不要把正常安装它作为离线开发前提。官方 SDK 可以单独安装 `pip install '.[tushare]'`。

## 在线数据准备

使用现有可用 tinyshare 安装时：

```bash
export TINYSHARE_TOKEN='你的 tinyshare 凭据'
quantlab doctor --provider tinyshare --config configs/all_weather_rotation.toml --probe
quantlab data prepare --config configs/all_weather_rotation.toml
quantlab backtest --config configs/all_weather_rotation.toml --offline
```

官方 SDK 使用独立的 `TUSHARE_TOKEN`，并将配置的 `data.provider` 改为 `tushare`。不会自动跨服务复用 token，也不会自动切换后端。SDK 仅在 `prepare` 或显式 `doctor --probe` 时构建；回测**始终只读冻结快照，不发网络请求**。

首次数据准备可能较慢：历史成分股并集、逐股财务数据、复权因子和逐日涨跌停都需要权限与请求额度。限频请求有限重试；参数/字段错误终止，不伪装成空数据。权限不足会在研究模式中记录并降级。所有数据保存在配置的目录。

`doctor --probe` 对端点分别标记 verified、empty_unverified 或失败，并保存脱敏样本。SDK 存在不代表在线兼容已验证。当前仓库的离线测试不要求真实凭据；在线验收使用：

```bash
QUANTLAB_LIVE=1 QUANTLAB_PROVIDER=tinyshare pytest -m live
```

## 成交和策略约定

- 同日收盘判断并按收盘价格模拟成交；这是有乐观偏差的研究假设，不等于盘中或实盘验证。
- 月初调仓、随后对日初持仓风控、按实际卖出结果补仓。月中开始不立刻调仓。
- 原稿 ROE > 0.15 表示百分数口径的 0.15%，不是 15%。PS 使用 TTM，PCF 使用现金净流量 TTM。
- 未知或不同口径的财务条件显式记录近似；不能声称与聚宽选股逐项精确一致。ROIC_TTM 暂采用明确标记的 Tushare ROIC/100 代理。
- 原稿固定费用：佣金万三、最低 5 元、股票卖出税千一、默认零滑点；这不代表历史实际费率。
- 股票 T+1；五个基金暂按明确配置的保守 T+1，不能据此声称已验证其历史 T+0 资格。
- 账户以整数分记账，追加买入累加数量与成本，缺失行情使用最近有效估值且不成交。
- 公司行为支持登记日权益、除权日应收分红、支付日现金和上市日解锁送股；税务、零碎股处理会明确记录近似。数据源未提供的权益事件不能凭空复原。

`data.strict=true` 拒绝所有近似；跨供应商财务公式和历史修订不可验证时，严格运行可能中止，这是预期行为。研究模式会将近似完整写入报告，不静默跳过。

## 扩展与报告

策略只实现 `on_phase(phase, context, results)`，返回 `BuyValue`、`TargetValue` 或 `Keep`；不修改账户、不调用数据 SDK。配置 `strategy.factory = "your_module:YourStrategy"` 即可接入。详见 [开发指南](docs/DEVELOPMENT.md)。

每次运行输出独立实验目录，包含原稿兼容命名的交易/净值/摘要 CSV、订单拒绝原因、每日持仓、基准、参数、数据校验和、代码版本及全部质量事件。`--plot` 在安装 `.[plot]` 后导出图表。`trade_intents.csv` 是本次历史意图审计记录，不是当前可直接发送的实盘指令。

参阅 [接口契约](docs/TUSHARE_CONTRACT.md)、[原稿规则映射](docs/STRATEGY_MAPPING.md)、[验证记录](docs/VALIDATION.md)。旧目录仅保留入口包装；原始聚宽脚本在 docs 中作为研究参考，不会被运行时导入。
