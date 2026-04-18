# Tushare Pro (tinyshare) API 数据接口参考

调用方式：
```python
import tinyshare as ts
ts.set_token("your_token")
pro = ts.pro_api()
df = pro.xxx(ts_code="000001.SZ", start_date="20230101", end_date="20231231")
```

日期格式均为 `YYYYMMDD` 字符串。

**返回值说明**：tinyshare 返回值可能是 pandas DataFrame（新版）或 list[dict]（旧版）。使用时建议先判断或用 `pl.DataFrame(raw)` 转换。

---

## 1. daily — A股日线行情
https://tushare.pro/document/2?doc_id=27
```python
pro.daily(ts_code="", trade_date="", start_date="", end_date="", adj="")
```
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| ts_code | str | 否 | 股票代码（支持多个，逗号分隔） |
| trade_date | str | 否 | 交易日期 YYYYMMDD |
| start_date | str | 否 | 开始日期 YYYYMMDD |
| end_date | str | 否 | 结束日期 YYYYMMDD |

输出字段（11个）：

| 字段 | 描述 |
|------|------|
| `ts_code` | TS股票代码 |
| `trade_date` | 交易日期 |
| `open` | 开盘价 |
| `high` | 最高价 |
| `low` | 最低价 |
| `close` | 收盘价 |
| `pre_close` | 昨收价 |
| `change` | 涨跌额 |
| `pct_chg` | 涨跌幅(%) |
| `vol` | 成交量(手) |
| `amount` | 成交额(千元) |

**注意**：`adj` 参数用于复权（`None`=不复权, `"hfq"`=后复权, `"qfq"`=前复权），但官方参数表中未列出该参数，属于扩展参数。

---

## 2. fund_daily — 基金日线

```python
pro.fund_daily(ts_code="", trade_date="", start_date="", end_date="")
```
参数同 `daily`，字段也相同，但**不支持 `adj` 复权**。

---

## 3. daily_basic — 每日指标
https://tushare.pro/document/2?doc_id=32
```python
pro.daily_basic(
    ts_code="", trade_date="", start_date="", end_date="",
    fields="ts_code,trade_date,pe,pb,total_mv,circ_mv,eps,turnover_rate"
)
```
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| ts_code | str | 是 | 股票代码（二选一） |
| trade_date | str | 否 | 交易日期（二选一） |
| start_date | str | 否 | 开始日期 YYYYMMDD |
| end_date | str | 否 | 结束日期 YYYYMMDD |

输出字段（18个）：

| 字段 | 描述 |
|------|------|
| `ts_code` | TS代码 |
| `trade_date` | 交易日期 |
| `close` | 收盘价 |
| `turnover_rate` | 换手率 |
| `turnover_rate_f` | 换手率(自由流通) |
| `volume_ratio` | 量比 |
| `pe` | 市盈率 |
| `pe_ttm` | 市盈率(TTM) |
| `pb` | 市净率 |
| `ps` | 市销率 |
| `ps_ttm` | 市销率(TTM) |
| `dv_ratio` | 股息率 |
| `dv_ttm` | 股息率(TTM) |
| `total_share` | 总股本(万股) |
| `float_share` | 流通股本(万股) |
| `free_share` | 自由流通股本(万股) |
| `total_mv` | 总市值(万元) |
| `circ_mv` | 流通市值(万元) |

---

## 4. balancesheet — 资产负债表
https://tushare.pro/document/2?doc_id=36
```python
pro.balancesheet(
    ts_code="", ann_date="", start_date="", end_date="",
    period="", report_type="", comp_type=""
)
```
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| ts_code | str | 是 | 股票代码 |
| ann_date | str | 否 | 公告日期 YYYYMMDD |
| start_date | str | 否 | 公告日开始日期 |
| end_date | str | 否 | 公告日结束日期 |
| period | str | 否 | 报告期（如 20171231=年报, 20170630=半年报） |
| comp_type | str | 否 | 公司类型：1=一般工商业, 2=银行, 3=保险, 4=证券 |

**注意**：`start_date`/`end_date` 是按**公告日**筛选，不是报告期。如需按报告期筛选，用 `period` 参数。

常用输出字段（158个，以下为项目中使用的）：

| 字段 | 描述 |
|------|------|
| `ts_code` | TS股票代码 |
| `end_date` | 报告期 |
| `total_share` | 期末总股本 |
| `cap_rese` | 资本公积金 |
| `undistr_porfit` | 未分配利润（注意拼写：porfit 非 profit） |
| `total_assets` | 资产总计 |
| `total_liab` | 负债合计 |
| `inventories` | 存货（注意：不是 inventory） |
| `fix_assets` | 固定资产 |
| `intan_assets` | 无形资产 |
| `money_cap` | 货币资金 |
| `goodwill` | 商誉 |

**重要提醒**：
- 存货字段名为 `inventories`，不是 `inventory`
- 未分配利润字段名为 `undistr_porfit`（拼写为 porfit）

---

## 5. income — 利润表
https://tushare.pro/document/2?doc_id=33
```python
pro.income(
    ts_code="", ann_date="", start_date="", end_date="",
    period="", report_type="", comp_type=""
)
```
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| ts_code | str | 是 | 股票代码 |
| ann_date | str | 否 | 公告日期 YYYYMMDD |
| start_date | str | 否 | 公告日开始日期 |
| end_date | str | 否 | 公告日结束日期 |
| period | str | 否 | 报告期（如 20171231=年报） |
| comp_type | str | 否 | 公司类型：1=一般工商业, 2=银行, 3=保险, 4=证券 |

常用输出字段（94个，以下为项目中使用的）：

| 字段 | 描述 |
|------|------|
| `ts_code` | TS代码 |
| `end_date` | 报告期 |
| `revenue` | 营业收入（注意：不是 oper_revenue） |
| `total_revenue` | 营业总收入 |
| `oper_cost` | 减：营业成本 |
| `total_cogs` | 营业总成本 |
| `admin_exp` | 减：管理费用 |
| `sell_exp` | 减：销售费用 |
| `fin_exp` | 减：财务费用 |
| `total_profit` | 利润总额 |
| `n_income` | 净利润（含少数股东损益） |
| `n_income_attr_p` | 净利润（不含少数股东损益） |
| `operate_profit` | 营业利润 |
| `non_oper_income` | 加：营业外收入 |
| `non_oper_exp` | 减：营业外支出 |
| `income_tax` | 所得税费用 |
| `ebit` | 息税前利润 |
| `ebitda` | 息税折旧摊销前利润 |
| `rd_exp` | 研发费用 |
| `basic_eps` | 基本每股收益 |
| `diluted_eps` | 稀释每股收益 |
| `invest_income` | 加：投资净收益 |
| `oth_income` | 其他收益 |
| `credit_impa_loss` | 信用减值损失 |

**重要提醒**：
- 营业收入字段名为 `revenue`，不是 `oper_revenue`
- `total_revenue`（营业总收入）和 `revenue`（营业收入）是两个不同的字段

---

## 6. cashflow — 现金流量表
https://tushare.pro/document/2?doc_id=44
```python
pro.cashflow(
    ts_code="", ann_date="", start_date="", end_date="",
    period="", report_type="", comp_type="", is_calc=0
)
```
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| ts_code | str | 是 | 股票代码 |
| ann_date | str | 否 | 公告日期 YYYYMMDD |
| start_date | str | 否 | 公告日开始日期 |
| end_date | str | 否 | 公告日结束日期 |
| period | str | 否 | 报告期 |
| comp_type | str | 否 | 公司类型：1=一般工商业, 2=银行, 3=保险, 4=证券 |
| is_calc | int | 否 | 是否计算报表 |

常用输出字段（97个，以下为项目中使用的）：

| 字段 | 描述 |
|------|------|
| `ts_code` | TS股票代码 |
| `end_date` | 报告期 |
| `n_cashflow_act` | 经营活动产生的现金流量净额 |
| `net_profit` | 净利润 |
| `c_fr_sale_sg` | 销售商品、提供劳务收到的现金 |
| `c_paid_goods_s` | 购买商品、接受劳务支付的现金 |
| `c_paid_to_for_empl` | 支付给职工以及为职工支付的现金 |
| `c_paid_for_taxes` | 支付的各项税费 |
| `finan_exp` | 财务费用 |
| `depr_fa_coga_dpba` | 固定资产折旧、油气资产折耗 |
| `free_cashflow` | 企业自由现金流量 |
| `cfps` | 每股现金流量净额（注意：可能不存在，用 ncfps 替代） |
| `ncfps` | 每股经营活动产生的现金流量净额 |
| `n_cashflow_inv_act` | 投资活动产生的现金流量净额 |
| `n_cash_flows_fnc_act` | 筹资活动产生的现金流量净额 |

**重要提醒**：`cfps` 在部分版本中可能不存在，可使用 `ncfps`（每股经营活动产生的现金流量净额）或 `n_cashflow_act / total_share` 计算。

---

## 7. fina_indicator — 财务指标
https://tushare.pro/document/2?doc_id=79
```python
pro.fina_indicator(
    ts_code="", ann_date="", start_date="", end_date="",
    fields=""
)
```
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| ts_code | str | 是 | TS股票代码 |
| ann_date | str | 否 | 公告日期 |
| start_date | str | 否 | 报告期开始日期 |
| end_date | str | 否 | 报告期结束日期 |
| period | str | 否 | 报告期（每个季度最后一天，如 20171231=年报） |

输出字段共 **168 个**，以下为常用字段：

### 盈利能力
| 字段 | 描述 |
|------|------|
| `roe` | 净资产收益率 |
| `roe_dt` | 净资产收益率(扣除非经常损益) |
| `roe_yearly` | 年化净资产收益率 |
| `roa` | 总资产报酬率 |
| `roa2_yearly` | 年化总资产报酬率 |
| `npta` | 总资产净利润 |
| `roic` | 投入资本回报率 |
| `netprofit_margin` | 销售净利率 |
| `grossprofit_margin` | 销售毛利率 |
| `cogs_of_sales` | 销售成本率 |
| `expense_of_sales` | 销售期间费用率 |
| `profit_to_gr` | 净利润/营业总收入 |
| `op_of_gr` | 营业利润/营业总收入 |
| `ebit_of_gr` | 息税前利润/营业总收入 |
| `profit_to_op` | 利润总额/营业收入 |

### 费用占比
| 字段 | 描述 |
|------|------|
| `adminexp_of_gr` | 管理费用/营业总收入 |
| `finaexp_of_gr` | 财务费用/营业总收入 |
| `saleexp_to_gr` | 销售费用/营业总收入 |
| `gc_of_gr` | 营业总成本/营业总收入 |

### 每股指标
| 字段 | 描述 |
|------|------|
| `eps` | 基本每股收益 |
| `dt_eps` | 稀释每股收益 |
| `bps` | 每股净资产 |
| `cfps` | 每股现金流量净额 |
| `ocfps` | 每股经营活动产生的现金流量净额 |
| `undist_profit_ps` | 每股未分配利润 |
| `revenue_ps` | 每股营业收入 |
| `ebit_ps` | 每股息税前利润 |
| `fcff_ps` | 每股企业自由现金流量 |
| `fcfe_ps` | 每股股东自由现金流量 |

### 增长指标
| 字段 | 描述 |
|------|------|
| `or_yoy` | 营业收入同比增长率 |
| `tr_yoy` | 营业总收入同比增长率 |
| `netprofit_yoy` | 归属母公司股东的净利润同比增长率 |
| `op_yoy` | 营业利润同比增长率 |
| `ocf_yoy` | 经营活动产生的现金流量净额同比增长率 |
| `equity_yoy` | 净资产同比增长率 |
| `basic_eps_yoy` | 基本每股收益同比增长率 |

### 偿债与杠杆
| 字段 | 描述 |
|------|------|
| `debt_to_assets` | 资产负债率 |
| `assets_to_eqt` | 权益乘数 |
| `current_ratio` | 流动比率 |
| `quick_ratio` | 速动比率 |
| `cash_ratio` | 保守速动比率 |
| `debt_to_eqt` | 产权比率 |
| `interestdebt` | 带息债务 |
| `netdebt` | 净债务 |
| `longdeb_to_debt` | 非流动负债/负债合计 |
| `currentdebt_to_debt` | 流动负债/负债合计 |

### 营运能力
| 字段 | 描述 |
|------|------|
| `inv_turn` | 存货周转率 |
| `ar_turn` | 应收账款周转率 |
| `ca_turn` | 流动资产周转率 |
| `fa_turn` | 固定资产周转率 |
| `assets_turn` | 总资产周转率 |
| `invturn_days` | 存货周转天数 |
| `arturn_days` | 应收账款周转天数 |
| `turn_days` | 营业周期 |

### 现金流
| 字段 | 描述 |
|------|------|
| `ebit` | 息税前利润 |
| `ebitda` | 息税折旧摊销前利润 |
| `fcff` | 企业自由现金流量 |
| `fcfe` | 股权自由现金流量 |
| `working_capital` | 营运资金 |
| `tangible_asset` | 有形资产 |

### 其他
| 字段 | 描述 |
|------|------|
| `extra_item` | 非经常性损益 |
| `rd_exp` | 研发费用 |
| `profit_dedt` | 扣除非经常性损益后的净利润 |
| `gross_margin` | 毛利 |
| `q_eps` | 每股收益(单季度) |
| `q_roe` | 净资产收益率(单季度) |
| `q_netprofit_margin` | 销售净利率(单季度) |

**重要提醒**：此接口**不包含**利润表/资产负债表原始字段。以下字段不在 fina_indicator 中，需通过对应接口获取：
- `n_income`, `total_profit`, `oper_cost` → 用 `income` 接口
- `revenue` → 用 `income` 接口（fina_indicator 有 `revenue_ps` 每股版本）
- `admin_exp` → 用 `income` 接口（fina_indicator 有 `adminexp_of_gr` 比例版本）
- `inventories`, `total_assets`, `total_liab` → 用 `balancesheet` 接口
- `n_cashflow_act` → 用 `cashflow` 接口

---

## 8. stock_basic — 股票列表
https://tushare.pro/document/2?doc_id=25
```python
pro.stock_basic(exchange="", list_status="L", fields="ts_code,symbol,name,area,industry,list_date")
```
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| ts_code | str | 否 | TS股票代码 |
| name | str | 否 | 名称 |
| market | str | 否 | 市场类别（主板/创业板/科创板/CDR/北交所） |
| list_status | str | 否 | L=上市, D=退市, P=暂停上市, G=过会未交易 |
| exchange | str | 否 | SSE=上交所, SZSE=深交所, BSE=北交所 |
| is_hs | str | 否 | N=否, H=沪股通, S=深股通 |

输出字段（17个）：

| 字段 | 描述 |
|------|------|
| `ts_code` | TS代码 |
| `symbol` | 股票代码 |
| `name` | 股票名称 |
| `area` | 地域 |
| `industry` | 所属行业 |
| `cnspell` | 拼音缩写 |
| `market` | 市场类型 |
| `list_date` | 上市日期 |
| `delist_date` | 退市日期 |
| `is_hs` | 是否沪深港通标的 |
| `act_name` | 实控人名称 |
| `act_ent_type` | 实控人企业性质 |
| `fullname` | 股票全称 |

---

## 9. index_weight — 指数成分和权重

### 第一优先：akshare（推荐，无需 token）
https://tushare.pro/document/2?doc_id=96
```python
import akshare as ak

df = ak.index_stock_cons(symbol="000852")  # 中证1000
df['symbol'] = df['品种代码'].apply(ak.stock_a_code_to_symbol)
df['ts_code'] = df['symbol'].str[2:] + '.' + df['symbol'].str[:2].str.upper()
# 去重（akshare 会返回同一股票多条记录）
df = df.drop_duplicates(subset=['ts_code'])
ts_codes = df['ts_code'].tolist()
```
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| symbol | str | 是 | 指数代码，如 "000852"（中证1000） |

输出列：`品种代码, 品种名称, 纳入日期` → 转换后 `ts_code` 格式为 `000001.SZ`

### 第二优先：tushare pro（需 token + 积分权限）
```python
pro.index_weight(index_code="", trade_date="", start_date="", end_date="")
```
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| index_code | str | 是 | 指数代码，如 000852.SH |
| trade_date | str | 否 | 交易日期 YYYYMMDD |
| start_date | str | 否 | 开始日期 |
| end_date | str | 否 | 结束日期 |

输出字段：`index_code, index_name, trade_date, con_code, con_name, weight`

注意：tushare 的 index_weight 是月度数据，建议输入月份的起止日期查询。部分指数需要较高积分权限，超时或无权限时改用 akshare。

---

## 不确定时查询官方文档

**重要**：如果需要使用未在此列出的字段，或不确定某个接口的正确用法，**必须通过 Playwright 浏览器抓取对应的官方文档页面确认**：

```python
import asyncio
from playwright.async_api import async_playwright

async def fetch_doc(doc_id):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(f"https://tushare.pro/document/2?doc_id={doc_id}", wait_until="networkidle", timeout=30000)
        tables = await page.query_selector_all("table")
        for table in tables:
            rows = await table.query_selector_all("tr")
            for row in rows:
                cells = await row.query_selector_all("td, th")
                texts = [await c.inner_text() for c in cells]
                print(texts)
        await browser.close()

asyncio.run(fetch_doc(79))  # 替换 doc_id
```

各接口的官方文档 URL（doc_id 对应关系）：

| 接口 | doc_id | URL |
|------|--------|-----|
| stock_basic | 25 | https://tushare.pro/document/2?doc_id=25 |
| daily | 27 | https://tushare.pro/document/2?doc_id=27 |
| fund_daily | — | 参数同 daily，无 adj |
| daily_basic | 32 | https://tushare.pro/document/2?doc_id=32 |
| balancesheet | 36 | https://tushare.pro/document/2?doc_id=36 |
| income | 33 | https://tushare.pro/document/2?doc_id=33 |
| cashflow | 44 | https://tushare.pro/document/2?doc_id=44 |
| fina_indicator | 79 | https://tushare.pro/document/2?doc_id=79 |
| index_weight | 96 | https://tushare.pro/document/2?doc_id=96（优先用 akshare） |

---

## 注意事项

1. **日期格式**：全部使用 `YYYYMMDD` 格式（如 `20230101`），不是 `YYYY-MM-DD`
2. **ts_code 格式**：`000001.SZ`（深圳）/ `600000.SH`（上海）
3. **财报数据**：返回的是季度/年度报告数据，`end_date` 是报告期（如 20231231 表示年报），**不是公告日期**
4. **空值处理**：财报字段可能为 None 或空值，合并后需要做 forward_fill
5. **权限限制**：部分高级接口需要 Tushare 积分 >= 2000
6. **fund_daily vs daily**：基金用 `fund_daily`，股票用 `daily`；基金无复权
7. **返回值类型**：tinyshare 可能返回 pandas DataFrame 或 list[dict]，需适配两种类型
8. **start_date/end_date 含义**：在财报接口中，这两个参数是按**公告日**筛选，不是报告期；如需按报告期筛选，用 `period` 参数

## 标准调用模板
```python
import tinyshare as ts

ts.set_token("your_token")
pro = ts.pro_api()

# 日线数据
df = pro.daily(ts_code="000001.SZ", start_date="20230101", end_date="20231231", adj="hfq")

# 每日指标
df = pro.daily_basic(ts_code="000001.SZ", start_date="20230101", end_date="20231231",
                      fields="ts_code,trade_date,pe,pb,total_mv,circ_mv,eps")

# 利润表（注意：start_date/end_date 是按公告日筛选）
df = pro.income(ts_code="000001.SZ", start_date="20230101", end_date="20231231")
# 常用字段：revenue（不是 oper_revenue）, oper_cost, n_income, total_profit, admin_exp

# 资产负债表
df = pro.balancesheet(ts_code="000001.SZ", start_date="20230101", end_date="20231231")
# 常用字段：total_assets, total_liab, inventories（不是 inventory）, undistr_porfit（拼写如此）

# 现金流量表
df = pro.cashflow(ts_code="000001.SZ", start_date="20230101", end_date="20231231")
# 常用字段：n_cashflow_act

# 财务指标
df = pro.fina_indicator(ts_code="000001.SZ", start_date="20230101", end_date="20231231")
# 常用字段：roe, debt_to_assets, netprofit_margin, cfps, or_yoy
# 注意：fina_indicator 不包含利润表/资产负债表原始字段
```
