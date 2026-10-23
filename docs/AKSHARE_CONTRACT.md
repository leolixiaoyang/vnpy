# AKShare 接口评估与实现契约

2026-10-23 核对官方 1.19.1 文档、对应 SDK 源码并执行有限在线抽样。结论：能满足当前全天候轮动策略的研究模式，不能提供完整、精确、无幸存者偏差的历史复现。策略及账户层不依赖 AKShare，核心安装仍可独立离线运行。

## 需求与覆盖

| 策略需求 | 接入的 AKShare 函数 | 处理和限制 |
| --- | --- | --- |
| 交易日历 | `tool_trade_date_hist_sina` | 开市日期构造日历；请求超出已返回日历边界时报错，不能把未知日期当休市 |
| 股票名称、上市日期 | `stock_profile_cninfo`；也支持 `stock_info_sh_name_code` / `stock_info_sz_name_code` 批量查询 | 准备流程按成分/备用池逐股查巨潮上市日，避免批量接口瞬时故障阻塞；当前名称、退市及停牌上市状态历史不完整，记录幸存者偏差 |
| 指数行情 | `stock_zh_index_daily_em`，失败后 `stock_zh_index_daily` | SH/SZ 前缀；新浪可能没有成交额，指数成交量单位不确定则留空；信号只使用收盘价 |
| 指数成分 | `index_stock_cons_weight_csindex` / `index_detail_hist_cni` | 保留源真实日期，不把最新成分回填历史；CNI 名称含 hist 也不保证返回多年成分 |
| 股票日行情 | `stock_zh_a_hist`，失败后 `stock_zh_a_daily` | 原始价格用于成交；复权信号单独处理；备用源及前收盘近似写入质量记录 |
| ETF / LOF 行情 | `fund_etf_hist_em` / `fund_lof_hist_em`，失败后 `fund_etf_hist_sina` | `164824.SZ` 显式走 LOF 主源；新浪函数文档也支持 LOF；未知行情保持缺失 |
| 基金名称/类型 | `fund_name_em` | 当前元数据，不伪造上市/退市日期；基金结算制度继续由 instruments 显式配置 |
| 市值、PE/PB/PS | `stock_value_em` | 按股票整段查询，按月调仓所需日期精确截取；总/流通市值为元，股本为股；PS 对应 PS_TTM |
| EPS、ROE、ROA、毛利/净利率 | `stock_financial_analysis_indicator_em` | 分别查询按报告期和按单季度；季度表没有公告日，关联同报告期累计表的 NOTICE_DATE，并记录这一假设 |
| 营收、营业利润增长率 | `stock_profit_sheet_by_report_em` | 季度值由 YTD 差分，增长率见下文；缺少必需报告时保持缺失 |
| 未分配利润、资产负债率条件 | `stock_balance_sheet_by_report_em` | 未分配利润、总负债、含少数股东权益分别映射，金额保持元 |
| 现金净流量市现率 | `stock_cash_flow_sheet_by_report_em` | CCE_ADD → n_incr_cash_cash_equ；由框架用历史可见累计报表计算 TTM；不使用经营现金流市现率代替 |
| 股票分红送转 | `stock_dividend_cninfo` | 每10股现金/送/转比例除10；登记、除权、派息、股份到账分别保留；不含完整配股等事件模型 |
| 基金分红 | `fund_fh_em(year=..., page=-1)` | 查询覆盖期各年全部页面，跨基金复用；现金为元/份，无公告日期，拆分/转换覆盖不足 |
| 历史涨跌停、历史 ST | 没有接入能证明完整覆盖的函数 | 标记不可用；沿用框架的价格限制估计及当前名称近似，不用最新涨停池伪造历史 |

中证最新成分、国证实际返回的快照可能全部晚于回测终点，此时历史成分表为空。框架只使用显式 `fallback_pools`，不会拿当前全部成分反填 2018 年。该备用池本身包含人工选样与幸存者偏差，不适合据此推断原指数策略的无偏收益。

## 字段、单位与时点

适配器输出共用的原始表契约（表名沿用 Tushare），然后由同一个 normalization 层转换成元、股、ISO 日期。**选 AKShare 不会调用 Tushare 服务，也不读取任何 token。**

- 东财股票/基金成交量是手，成交额是元；中间成交额除1000后由 normalization 乘1000，避免重复放大。新浪股票成交量为股，中间先除100。
- 新浪基金文档标注成交量为手，但在线 KLC 样本的 `amount / volume` 对应实际单价，表明样本为股。适配器用成交额、成交量和价格的比值判断股/手并记录推断；缺额或比例无法确认则成交量留空，账户拒绝该行情成交。不会静默应用100倍比例。
- `stock_value_em` 的市值和股本先除10000，再经标准 normalization 还原为元和股；不拿当前市值回填缺失历史。`市销率` 的源码字段为 PS_TTM；`市现率` 是 PCF_OCF_TTM，故不用于原稿的 PCF_NET_TTM。
- 财务指标保留百分数数值。季度 EPSJB、ROE_DILUTED、JROA、NET_PROFIT_RATIO、GROSS_PROFIT_RATIO 映射至季度指标；累计 ROEJQ 为加权 ROE，与季度摊薄 ROE 不同，不能宣称与聚宽公式完全一致。ROIC/100 仍是报告 ROIC 代理。
- 营业收入/营业利润季度值为本期 YTD 减同年上季度 YTD，第一季度直接采用本期值；必须存在准确对应报告期。同比为 `(本期-上年同期)/abs(上年同期)*100`，零分母缺失。可用日期取全部使用报表公告日的最大值，缺少输入不补零。推导公式会记录为跨源近似。
- 三表使用合并、累计报告。可见性按公告日期，公告当日仍不可见；缺公告日的报表剔除，不以报告期末替代。上游当前修订值不构成完整历史修订记录，研究模式明确记录风险。
- 调整因子由同源后复权/原始收盘价比值构造，属于供应商调整公式近似。基金仅新浪原始行情可用时，复权因子保持不可用，信号退化为未复权并记录；成交仍使用原始价。公司行为单独入账，不能拿复权价直接成交。
- 巨潮有时将同一除权日的现金分红和送转分成两条公告。仅在登记日一致、恰好一条纯现金及一条纯送转、公告日明确时合并，并采用较晚公告日及各自的派息/到账日，记录转换；两条现金等含糊冲突仍拒绝。账户初始持仓为空，公司行为表只取回测区间内除权日，区间外历史事件不会阻塞本次准备。

非空响应出现缺失必要列、非法数值、冲突重复报告、或未支持的过滤参数会终止；上游连接/返回格式异常以已脱敏的 ProviderError 降级。缺失值保留为 NaN。所有源切换、覆盖边界和推导假设随原始缓存保存，命中缓存后仍重放至质量日志；`strict=true` 拒绝这些近似。

`stock_value_em` SDK 目前只请求一页5000行，财务指标请求最多200期；即使请求很长区间也不能保证接口返回完整历史。表内缺日期不扩展、不向前填充；估值/价格覆盖区间写入质量记录。原始历史的本次进程内复用避免每个月重复抓取同一股票，但首次准备仍可能较慢。

## 配置与执行

```toml
[data]
provider = "akshare" # 默认；另可选择 tushare、tinyshare
snapshot = "../data/all_weather_akshare"
cache = "../.quantlab/cache"
strict = false

[data.akshare]
lof_symbols = ["164824.SZ"]
```

```bash
python -m pip install -e '.[akshare]'
quantlab doctor --config configs/all_weather_rotation.toml --probe
quantlab data prepare --config configs/all_weather_rotation.toml
quantlab backtest --config configs/all_weather_rotation.toml --offline
```

`--provider` 可覆盖 doctor/data prepare 的配置。已有旧配置显式指定 tinyshare/tushare 时尊重该值；省略配置则用 akshare。切换后重新准备到独立快照目录，回测只认快照里实际保存的数据与供应商 provenance。离线回测及普通 doctor 不导入任何在线 SDK。

doctor 的 verified 表示本次接口非空且通过字段契约；empty_unverified 不算通过；已知不可用数据标记 unsupported。`online_verified` 仅汇总受支持接口的本次探测，`full_strategy_coverage_verified=false` 单独说明历史覆盖尚未证明。股票/基金行情、财报和历史成分可分别失败，不能凭一个成功响应宣称完整回测可用。

## 官方资料

- [AKShare 股票接口文档](https://akshare.akfamily.xyz/data/stock/stock.html)
- [AKShare 基金接口文档](https://akshare.akfamily.xyz/data/fund/fund_public.html)
- [AKShare 指数接口文档](https://akshare.akfamily.xyz/data/index/index.html)
- [历史估值源码：PS_TTM / PCF_OCF_TTM 与分页上限](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_value_em.py)
- [财务指标源码：按报告期/按单季度](https://github.com/akfamily/akshare/blob/main/akshare/stock_fundamental/stock_finance_sina.py)
- [合并三表源码](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_three_report_em.py)
- [股票分红源码](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_dividend_cninfo.py)
- [基金分红及拆分源码](https://github.com/akfamily/akshare/blob/main/akshare/fund/fund_fhsp_em.py)
