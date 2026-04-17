# 克隆自聚宽文章：https://www.joinquant.com/post/69905
# 标题：懒人小市值
# 作者：ZHB_X_QUANT

# ================= 初始化 =================
def initialize(context):
    set_benchmark('000905.XSHG')
    set_option('use_real_price', True)
    set_option('order_volume_ratio', 1)
    set_option('avoid_future_data', True)

    set_order_cost(OrderCost(
        open_tax=0,
        close_tax=0.001,
        open_commission=0.0003,
        close_commission=0.0003,
        min_commission=5
    ), type='stock')

    g.stock_num = 20
    g.query_pool_num = 400
    g.small_cap_pool_num = 100
    g.min_listing_days = 365
    g.rebalance_interval = 7
    g.day_count = 0
    g.empty_months = [1, 4]

    # 杠铃策略配置（帖子核心优化：资产配置控制回撤）
    g.gold_etf = '518880.XSHG'
    g.stock_ratio = 0.5
    g.gold_ratio = 0.5
    g.enable_barbell = True

    # 止损配置
    g.stop_loss_rate = 0.08
    g.drop_filter_days = 5

    run_daily(trade, '14:50')


# ================= 主流程 =================
def trade(context):
    check_stop_loss(context)

    if is_empty_window(context):
        clear_position(context)
        g.day_count = 0
        return

    if g.day_count % g.rebalance_interval != 0:
        g.day_count += 1
        return

    target_list = select_stocks(context)
    adjust_position(context, target_list)
    g.day_count = 1


# ================= 选股 =================
def select_stocks(context):
    q = query(
        valuation.code,
        valuation.circulating_market_cap,
        valuation.pb_ratio,
        valuation.pe_ratio,
        indicator.roe,
        income.net_profit,
        cash_flow.net_operate_cash_flow
    ).filter(
        valuation.circulating_market_cap > 0,
        valuation.pb_ratio > 0,
        valuation.pe_ratio > 0,
        valuation.pe_ratio < 50,
        indicator.roe > 0.05,
        income.net_profit > 0,
        cash_flow.net_operate_cash_flow > 0
    ).order_by(
        valuation.circulating_market_cap.asc()
    ).limit(
        g.query_pool_num
    )

    df = get_fundamentals(q)
    if df is None or len(df) == 0:
        return []

    stock_list = list(df['code'])
    stock_list = filter_main_board_stock(stock_list)
    stock_list = filter_paused_stock(stock_list)
    stock_list = filter_st_stock(stock_list)
    stock_list = filter_new_stock(context, stock_list)
    stock_list = filter_big_drop_stock(stock_list)

    if len(stock_list) == 0:
        return []

    df = df[df['code'].isin(stock_list)].sort_values('circulating_market_cap').head(g.small_cap_pool_num)
    stock_list = list(df['code'])
    market_cap_map = dict(zip(df['code'], df['circulating_market_cap']))

    final_list = []
    for stock in stock_list:
        try:
            hist = attribute_history(stock, 60, '1d', ['close'], skip_paused=True)
            close = hist['close']
            if len(close) < 40:
                continue

            current_price = close.iloc[-1]
            if current_price < 2:
                continue

            returns = close.pct_change().dropna()
            vol20 = returns.tail(20).std()
            if vol20 >= 0.07:
                continue

            ma10 = close.tail(10).mean()
            ma20 = close.tail(20).mean()
            if current_price < ma10 * 0.98:
                continue
            if ma10 < ma20 * 0.97:
                continue

            final_list.append((
                stock,
                vol20,
                market_cap_map[stock],
                current_price,
                close.tail(5).mean() / current_price
            ))
        except:
            continue

    final_list = sorted(final_list, key=lambda item: item[1:])
    return [item[0] for item in final_list[:g.stock_num]]


# ================= 调仓 =================
def adjust_position(context, target_list):
    hold_list = list(context.portfolio.positions.keys())
    stock_holdings = [s for s in hold_list if s != g.gold_etf]

    for stock in stock_holdings:
        if stock not in target_list:
            order_target_value(stock, 0)

    if len(target_list) == 0:
        return

    if g.enable_barbell:
        stock_value = context.portfolio.total_value * g.stock_ratio / len(target_list)
        gold_value = context.portfolio.total_value * g.gold_ratio
        order_target_value(g.gold_etf, gold_value)
    else:
        stock_value = context.portfolio.total_value / len(target_list)

    for stock in target_list:
        if can_buy_stock(stock):
            order_target_value(stock, stock_value)


def clear_position(context):
    for stock in list(context.portfolio.positions.keys()):
        if stock == g.gold_etf:
            continue
        order_target_value(stock, 0)


# ================= 止损 =================
def check_stop_loss(context):
    for stock in list(context.portfolio.positions.keys()):
        if stock == g.gold_etf:
            continue
        position = context.portfolio.positions[stock]
        current_data = get_current_data()[stock]
        if current_data.last_price == 0 or position.avg_cost == 0:
            continue
        loss_rate = (position.avg_cost - current_data.last_price) / position.avg_cost
        if loss_rate >= g.stop_loss_rate:
            order_target_value(stock, 0)


# ================= 时间过滤 =================
def is_empty_window(context):
    return context.current_dt.month in g.empty_months


# ================= 工具函数 =================
def filter_main_board_stock(stock_list):
    result = []
    for stock in stock_list:
        if stock.startswith(('300', '301', '688', '689', '8', '4')):
            continue
        result.append(stock)
    return result


def filter_paused_stock(stock_list):
    current_data = get_current_data()
    return [stock for stock in stock_list if not current_data[stock].paused]


def filter_st_stock(stock_list):
    current_data = get_current_data()
    return [
        stock for stock in stock_list
        if not current_data[stock].is_st
        and 'ST' not in current_data[stock].name
        and '*' not in current_data[stock].name
        and '退' not in current_data[stock].name
    ]


def filter_new_stock(context, stock_list):
    current_dt = context.current_dt.date()
    return [
        stock for stock in stock_list
        if (current_dt - get_security_info(stock).start_date).days >= g.min_listing_days
    ]


def filter_big_drop_stock(stock_list):
    """过滤近期有单日暴跌(>8%)的股票，避免接飞刀"""
    result = []
    for stock in stock_list:
        try:
            hist = attribute_history(stock, g.drop_filter_days, '1d', ['close'], skip_paused=True)
            close = hist['close']
            if len(close) < 2:
                result.append(stock)
                continue
            daily_returns = close.pct_change().dropna()
            if (daily_returns <= -g.stop_loss_rate).any():
                continue
            result.append(stock)
        except:
            continue
    return result


def can_buy_stock(stock):
    current_data = get_current_data()[stock]
    if current_data.paused:
        return False
    if current_data.last_price >= current_data.high_limit:
        return False
    if current_data.last_price <= current_data.low_limit:
        return False
    return True
