# Tushare Pro (tinyshare) API 数据接口参考

调用方式：
```python
import tinyshare as ts
ts.set_token("your_token")
pro = ts.pro_api()
df = pro.xxx(ts_code="000001.SZ", start_date="20230101", end_date="20231231")
```

日期格式均为 `YYYYMMDD` 字符串。返回值是 list[dict] 或 None。

---

## 1. daily — A股日线行情
https://tushare.pro/document/2?doc_id=27
```python
pro.daily(ts_code="", trade_date="", start_date="", end_date="", adj="")
```
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| ts_code | str | 否 | 股票代码，如 000001.SZ |
| trade_date | str | 否 | 交易日期 YYYYMMDD |
| start_date | str | 否 | 开始日期 |
| end_date | str | 否 | 结束日期 |
| adj | str | 否 | 复权类型：`None`=不复权, `"hfq"`=后复权, `"qfq"`=前复权 |

常用输出字段：`ts_code, trade_date, open, high, low, close, pre_close, change, pct_chg, vol, amount`

---

## 2. fund_daily — 基金日线
```python
pro.fund_daily(ts_code="", start_date="", end_date="")
```
参数同 `daily`，但不支持 `adj` 复权。

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
| ts_code | str | 否 | 股票代码 |
| trade_date | str | 否 | 交易日期 |
| start_date | str | 否 | 开始日期 |
| end_date | str | 否 | 结束日期 |
| fields | str | 否 | 字段列表（逗号分隔） |

常用 fields：`ts_code, trade_date, pe, pb, ps, total_mv, circ_mv, eps, dps, turnover_rate, turnover_rate_f`

---

## 4. balancesheet — 资产负债表
https://tushare.pro/document/2?doc_id=36
```python
pro.balancesheet(
    ts_code="", ann_date="", start_date="", end_date="",
    fields=""
)
```
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| ts_code | str | 否 | 股票代码 |
| ann_date | str | 否 | 公告日期 |
| start_date | str | 否 | 报告期开始 |
| end_date | str | 否 | 报告期结束 |
| fields | str | 否 | 字段列表 |

常用 fields：`ts_code, end_date, total_liab, total_assets, inventories, undistr_porfit, total_share`

**注意**：存货字段名为 `inventories`（不是 `inventory`），未分配利润字段名为 `undistr_porfit`（拼写如此）。

---

## 5. income — 利润表
https://tushare.pro/document/2?doc_id=33
```python
pro.income(
    ts_code="", ann_date="", start_date="", end_date="",
    fields=""
)
```
常用 fields：`ts_code, end_date, n_income, total_profit, oper_cost, revenue, admin_exp`

**注意**：营业收入字段名为 `revenue`（不是 `oper_revenue`）。

---

## 6. cashflow — 现金流量表
https://tushare.pro/document/2?doc_id=44
```python
pro.cashflow(
    ts_code="", ann_date="", start_date="", end_date="",
    fields=""
)
```
常用 fields：`ts_code, end_date, n_cashflow_act`

---

## 7. fina_indicator — 财务指标
https://tushare.pro/document/2?doc_id=79
```python
pro.fina_indicator(
    ts_code="", ann_date="", start_date="", end_date="",
    fields=""
)
```
常用 fields：`ts_code, end_date, roe, eps_dt, debt_to_assets, bps_urps, or_yoy, ncfps, admin_exp, n_income, oper_revenue, net_profit_margin, non_operate_profit`

---

## 8. stock_basic — 股票列表
https://tushare.pro/document/2?doc_id=25
```python
pro.stock_basic(exchange="", list_status="L", fields="ts_code,symbol,name,area,industry,list_date")
```
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| exchange | str | 否 | 交易所：SSE/SZSE |
| list_status | str | 否 | L=上市, D=退市, P=暂停上市 |
| fields | str | 否 | 字段列表 |

---

## 9. index_weight — 指数成分和权重

### 🥇 第一优先：akshare（推荐，无需 token）
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
| symbol | str | 是 | 指数代码，如 "000852"（中证1000），"000300"（沪深300），"000905"（中证500） |

输出列：`品种代码, 品种名称, 纳入日期` → 转换后 `ts_code` 格式为 `000001.SZ`

### 🥈 第二优先：tushare pro（需 token + 积分权限）
```python
pro.index_weight(index_code="", trade_date="", start_date="", end_date="")
```
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| index_code | str | 是 | 指数代码，如 000852.SH（中证1000） |
| trade_date | str | 否 | 交易日期 YYYYMMDD |
| start_date | str | 否 | 开始日期 |
| end_date | str | 否 | 结束日期 |

输出字段：`index_code, index_name, trade_date, con_code, con_name, weight`

注意：tushare 的 index_weight 是月度数据，建议输入月份的起止日期查询。部分指数需要较高积分权限，超时或无权限时改用 akshare。

---

## 不确定时查询官方文档

**重要**：以下列出的参数和字段名基于项目中已有的使用模式整理，可能不完整。如果需要使用未在此列出的字段，或不确定某个接口的正确用法，**必须通过 `WebFetch` 工具抓取对应的官方文档页面确认**：

```python
from WebFetch import web_fetch  # 伪代码示意
# 获取 doc_id 对应的官方文档，提取完整参数和输出字段列表
```

各接口的官方文档 URL（doc_id 对应关系）：

| 接口 | doc_id | URL |
|------|--------|-----|
| stock_basic | 25 | https://tushare.pro/document/2?doc_id=25 |
| daily | 27 | https://tushare.pro/document/2?doc_id=27 |
| fund_daily（无独立文档页，参数同 daily 无 adj） | — | — |
| daily_basic | 32 | https://tushare.pro/document/2?doc_id=32 |
| balancesheet | 36 | https://tushare.pro/document/2?doc_id=36 |
| income | 33 | https://tushare.pro/document/2?doc_id=33 |
| cashflow | 44 | https://tushare.pro/document/2?doc_id=44 |
| fina_indicator | 79 | https://tushare.pro/document/2?doc_id=79 |
| index_weight | 96 | https://tushare.pro/document/2?doc_id=96（优先用 akshare） |

**查询步骤**：当需要使用某个不在上方已记录字段列表中的新字段时，用 `WebFetch` 访问对应 doc_id 的文档页面，提取完整 fields 列表后再使用。如果 WebFetch 被拦截（网络限制），参考项目根目录 `tinyshare.md` 中的链接提示用户自行查阅。

---

## 注意事项

1. **日期格式**：全部使用 `YYYYMMDD` 格式（如 `20230101`），不是 `YYYY-MM-DD`
2. **ts_code 格式**：`000001.SZ`（深圳）/ `600000.SH`（上海）
3. **财报数据**：返回的是季度/年度报告数据，`end_date` 是报告期（如 20231231 表示年报），**不是公告日期**
4. **空值处理**：财报字段可能为 None 或空值，合并后需要做 forward_fill
5. **权限限制**：部分高级接口需要 Tushare 积分 >= 2000
6. **fund_daily vs daily**：基金用 `fund_daily`，股票用 `daily`；基金无复权

## 标准调用模板
```python
import tinyshare as ts

ts.set_token("your_token")
pro = ts.pro_api()

# 日线数据
df = pro.daily(ts_code="000001.SZ", start_date="20230101", end_date="20231231", adj="hfq")

# 基本面指标
df = pro.daily_basic(ts_code="000001.SZ", start_date="20230101", end_date="20231231",
                      fields="ts_code,trade_date,pe,pb,total_mv,circ_mv,eps")

# 财报数据（报告期范围查询）
df = pro.income(ts_code="000001.SZ", start_date="20230101", end_date="20231231",
                 fields="ts_code,end_date,n_income,total_profit,oper_cost,oper_revenue")

df = pro.balancesheet(ts_code="000001.SZ", start_date="20230101", end_date="20231231",
                       fields="ts_code,end_date,total_liab,total_assets,inventory,total_share")

df = pro.cashflow(ts_code="000001.SZ", start_date="20230101", end_date="20231231",
                   fields="ts_code,end_date,n_cashflow_act")

# 财务指标
df = pro.fina_indicator(ts_code="000001.SZ", start_date="20230101", end_date="20231231",
                          fields="ts_code,end_date,roe,eps_dt,debt_to_assets,net_profit_margin")
```
