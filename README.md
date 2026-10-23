# Quantlab：独立的轻量量化研究框架

Python 3.11+，不依赖 vnpy、聚宽、数据库服务或图形界面。核心提供数据快照、账户与成交、日线回测、策略协议和实验报告。第一个策略是聚宽全天候轮动的**日线收盘近似移植**。

## 安装与离线演示

```bash
python -m pip install -e '.[test]'
quantlab doctor
quantlab demo --output /tmp/quantlab-demo
quantlab backtest --config /tmp/quantlab-demo/demo.toml --offline
pytest
```

演示全部使用确定性的合成数据，不能作为真实收益证明。`demo.toml` 中的路径相对配置文件解析，安装后可以从任意目录运行。

核心安装不包含在线 SDK，离线开发无需安装数据源。**默认数据源是 AKShare，无需 token**；在线使用安装 `pip install -e '.[akshare]'`。官方 Tushare 可单独安装 `pip install -e '.[tushare]'`，tinyshare 保留为可选的现有 SDK 接入。

## 在线数据准备

使用默认 AKShare：

```bash
python -m pip install -e '.[akshare]'
quantlab doctor --config configs/all_weather_rotation.toml --probe
quantlab data prepare --config configs/all_weather_rotation.toml
quantlab backtest --config configs/all_weather_rotation.toml --offline
```

在 TOML 中选择数据源；省略 `provider` 也使用 `akshare`：

```toml
[data]
provider = "akshare" # akshare | tushare | tinyshare
```

`data prepare --provider tushare --config ...`、`doctor --provider tushare --config ...` 可以临时覆盖配置，不修改文件。Tushare 使用 `TUSHARE_TOKEN`，tinyshare 使用 `TINYSHARE_TOKEN`；不会跨服务复用 token 或自动切换数据源。AKShare 内部允许有记录地从东财行情切换到新浪行情。SDK 仅在 `prepare` 或显式 `doctor --probe` 时构建；回测**始终只读冻结快照，不发网络请求**。切换数据源后必须重新准备快照，建议为不同源配置独立的 `snapshot` 路径；只改配置不会替换旧快照。

AKShare 可满足当前策略的**研究模式**：日行情、历史市值/估值、季度财务指标、三张报表及分红均有接入。完整历史成分股、历史 ST、精确历史涨跌停、财报历史修订和基金拆分仍有缺口；不能据此宣称精确复现原稿。缺失历史成分股时使用配置中明确指定的备用股票池，会产生样本与幸存者偏差。部分上游站点可能临时不可用，空响应不证明覆盖完整。字段、单位、限制及实测记录见 [AKShare 接入说明](docs/AKSHARE_CONTRACT.md)。

首次准备可能较慢，逐股财务接口内部还会请求多个历史页面。AKShare 按股票获取整段历史估值并在本次准备中复用，只保存调仓所需日期；不重复请求不存在的历史涨跌停接口。原始缓存按供应商、SDK、映射版本和查询配置隔离，并保存质量记录，缓存命中后仍会将限制写入快照。参数/字段错误终止，网络或权限不足在研究模式中记录并降级，数据保存在配置的目录。AKShare 部分 SDK 函数没有超时参数；长期阻塞可中断后重试，已完成的原始缓存会复用。

`doctor --probe` 对端点分别标记 verified、empty_unverified、unsupported 或失败，并保存脱敏样本和质量记录。`online_verified` 只表示本次受支持接口探测成功，完整历史覆盖另记为未验证，已知缺口不计为成功接口。当前仓库的离线测试不要求在线 SDK 或真实凭据；在线验收使用：

```bash
QUANTLAB_LIVE=1 QUANTLAB_PROVIDER=akshare pytest -m live
```

## 成交和策略约定

- 同日收盘判断并按收盘价格模拟成交；这是有乐观偏差的研究假设，不等于盘中或实盘验证。
- 月初调仓、随后对日初持仓风控、按实际卖出结果补仓。月中开始不立刻调仓。
- 原稿 ROE > 0.15 表示百分数口径的 0.15%，不是 15%。PS 使用 TTM，PCF 使用现金净流量 TTM。
- 未知或不同口径的财务条件显式记录近似；不能声称与聚宽选股逐项精确一致。ROIC_TTM 暂采用明确标记的供应商报告 ROIC/100 代理。
- 原稿固定费用：佣金万三、最低 5 元、股票卖出税千一、默认零滑点；这不代表历史实际费率。
- 股票 T+1；五个基金暂按明确配置的保守 T+1，不能据此声称已验证其历史 T+0 资格。
- 账户以整数分记账，追加买入累加数量与成本，缺失行情使用最近有效估值且不成交。
- 公司行为支持登记日权益、除权日应收分红、支付日现金和上市日解锁送股；税务、零碎股处理会明确记录近似。数据源未提供的权益事件不能凭空复原。

`data.strict=true` 拒绝所有近似；跨供应商财务公式和历史修订不可验证时，严格运行可能中止，这是预期行为。研究模式会将近似完整写入报告，不静默跳过。

## 扩展与报告

策略只实现 `on_phase(phase, context, results)`，返回 `BuyValue`、`TargetValue` 或 `Keep`；不修改账户、不调用数据 SDK。配置 `strategy.factory = "your_module:YourStrategy"` 即可接入。详见 [开发指南](docs/DEVELOPMENT.md)。

每次运行输出独立实验目录，包含原稿兼容命名的交易/净值/摘要 CSV、订单拒绝原因、每日持仓、基准、参数、数据校验和、代码版本及全部质量事件。`--plot` 在安装 `.[plot]` 后导出图表。`trade_intents.csv` 是本次历史意图审计记录，不是当前可直接发送的实盘指令。

参阅 [AKShare 契约](docs/AKSHARE_CONTRACT.md)、[Tushare 契约](docs/TUSHARE_CONTRACT.md)、[原稿规则映射](docs/STRATEGY_MAPPING.md)、[验证记录](docs/VALIDATION.md)。旧目录仅保留入口包装；原始聚宽脚本在 docs 中作为研究参考，不会被运行时导入。
