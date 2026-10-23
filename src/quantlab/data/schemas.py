from dataclasses import dataclass

from ..quality import DataError


@dataclass(frozen=True)
class Schema:
    params: frozenset[str]
    fields: tuple[str, ...]
    required: tuple[str, ...]
    keys: tuple[str, ...]
    date_axis: str | None = "trade_date"
    cap: int = 5000


def schema(params, fields, required, keys, date_axis="trade_date", cap=5000):
    return Schema(frozenset(params.split()), tuple(fields.split()), tuple(required.split()),
                  tuple(keys.split()), date_axis, cap)


BAR = "ts_code trade_date open high low close pre_close vol amount"
DATES = "ts_code trade_date start_date end_date"
STATEMENT_DATES = "ts_code ann_date start_date end_date period report_type comp_type"
SCHEMAS = {
    "daily": schema(DATES, BAR, "ts_code trade_date close", "ts_code trade_date", cap=6000),
    "index_daily": schema(DATES, BAR, "ts_code trade_date close", "ts_code trade_date", cap=8000),
    "fund_daily": schema(DATES, BAR, "ts_code trade_date close", "ts_code trade_date"),
    "daily_basic": schema(DATES, "ts_code trade_date close pe pe_ttm pb ps ps_ttm total_share float_share free_share total_mv circ_mv", "ts_code trade_date total_mv circ_mv", "ts_code trade_date", cap=6000),
    "trade_cal": schema("exchange start_date end_date is_open", "exchange cal_date is_open pretrade_date", "cal_date is_open", "exchange cal_date", "cal_date", 10000),
    "stock_basic": schema("ts_code name exchange market list_status is_hs", "ts_code name market exchange list_status list_date delist_date", "ts_code list_date", "ts_code", None, 10000),
    "fund_basic": schema("ts_code market status", "ts_code name market status list_date delist_date fund_type", "ts_code", "ts_code", None, 15000),
    "index_basic": schema("ts_code name market publisher category", "ts_code name market publisher", "ts_code", "ts_code", None, 10000),
    "index_weight": schema("index_code trade_date start_date end_date", "index_code con_code trade_date weight", "index_code con_code trade_date", "index_code con_code trade_date"),
    "fina_indicator": schema("ts_code ann_date start_date end_date period", "ts_code ann_date end_date eps q_eps roe q_roe roa npta q_npta roic netprofit_margin grossprofit_margin q_netprofit_margin q_gsprofit_margin tr_yoy or_yoy op_yoy q_gr_yoy q_sales_yoy q_op_yoy update_flag", "ts_code ann_date end_date", "ts_code end_date ann_date", "end_date", 100),
    "income": schema(STATEMENT_DATES + " f_ann_date", "ts_code ann_date f_ann_date end_date report_type basic_eps revenue total_revenue operate_profit n_income n_income_attr_p", "ts_code ann_date end_date", "ts_code end_date ann_date report_type", "ann_date"),
    "balancesheet": schema(STATEMENT_DATES, "ts_code ann_date f_ann_date end_date report_type total_share total_assets total_liab total_hldr_eqy_inc_min_int undistr_porfit update_flag", "ts_code ann_date end_date", "ts_code end_date ann_date report_type", "ann_date"),
    "cashflow": schema(STATEMENT_DATES + " f_ann_date is_calc", "ts_code ann_date f_ann_date end_date report_type n_cashflow_act n_incr_cash_cash_equ update_flag", "ts_code ann_date end_date", "ts_code end_date ann_date report_type", "ann_date"),
    "stk_limit": schema(DATES, "ts_code trade_date pre_close up_limit down_limit", "ts_code trade_date up_limit down_limit", "ts_code trade_date", cap=5800),
    "adj_factor": schema(DATES, "ts_code trade_date adj_factor", "ts_code trade_date adj_factor", "ts_code trade_date", cap=6000),
    "fund_adj": schema(DATES + " offset limit", "ts_code trade_date adj_factor", "ts_code trade_date adj_factor", "ts_code trade_date", cap=2000),
    "namechange": schema("ts_code start_date end_date", "ts_code name start_date end_date ann_date change_reason", "ts_code name start_date", "ts_code start_date name", "start_date"),
    "dividend": schema("ts_code ann_date record_date ex_date imp_ann_date", "ts_code end_date ann_date div_proc stk_div cash_div cash_div_tax record_date ex_date pay_date div_listdate", "ts_code", "ts_code end_date ex_date ann_date div_proc", None, 2000),
    "fund_div": schema("ts_code ann_date ex_date pay_date", "ts_code ann_date imp_anndate base_date div_proc record_date ex_date pay_date earpay_date net_ex_date div_cash", "ts_code", "ts_code ex_date ann_date div_proc", None),
}


def validate_request(api: str, params: dict, fields: tuple[str, ...]):
    if api not in SCHEMAS:
        raise DataError(f"Unsupported endpoint: {api}")
    spec = SCHEMAS[api]
    unknown = set(params) - spec.params
    invalid = set(fields) - set(spec.fields)
    if unknown or invalid:
        raise DataError(f"{api}: unsupported params={sorted(unknown)} fields={sorted(invalid)}")
    for key, value in params.items():
        if key.endswith("date") or key == "period":
            if value and (len(str(value)) != 8 or not str(value).isdigit()):
                raise DataError(f"{api}.{key} must be YYYYMMDD")
