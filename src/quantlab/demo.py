"""Deterministic synthetic data, solely for installation and offline acceptance."""
from pathlib import Path

import pandas as pd

from .data.bundle import DataBundle


def demo_bundle():
    days = pd.bdate_range("2025-12-01", "2026-02-10").strftime("%Y-%m-%d").tolist()
    stock_codes = ["600000.SH", "600036.SH", "000001.SZ", "000002.SZ"]
    bars, limits, basic, factors = [], [], [], []
    for day_i, day in enumerate(days):
        for j, symbol in enumerate(stock_codes):
            # Small-cap momentum is stronger; a February drop exercises risk exits.
            price = round(10 + day_i * (.025 if j < 2 else .06), 2)
            if symbol == "000001.SZ" and day >= "2026-02-04":
                price = round(price * .88, 2)
            bars.append({"ts_code": symbol, "trade_date": day, "open": price, "high": price,
                         "low": price, "close": price, "pre_close": price, "volume": 100000})
            limits.append({"ts_code": symbol, "trade_date": day, "up_limit": price * 1.1, "down_limit": price * .9})
            factors.append({"ts_code": symbol, "trade_date": day, "adj_factor": 1.0})
            basic.append({"ts_code": symbol, "trade_date": day, "total_mv": 10e8 * (j + 1),
                          "circ_mv": 8e8 * (j + 1), "pe": 10.0, "pe_ttm": 10.0,
                          "ps_ttm": 2.0, "pb": 1.0})
    weights = []
    for index, stocks in [("000300.SH", stock_codes[:2]), ("399101.SZ", stock_codes[2:])]:
        weights.extend({"index_code": index, "con_code": symbol, "trade_date": days[0], "weight": 50.0} for symbol in stocks)
    financials = [{"ts_code": s, "ann_date": "2025-10-25", "end_date": "2025-09-30", "q_eps": .5,
                   "q_roe": 2.0, "q_npta": 1.0, "q_netprofit_margin": 10.0,
                   "q_gsprofit_margin": 20.0, "q_sales_yoy": 1.0, "q_gr_yoy": 1.0,
                   "q_op_yoy": 1.0, "roic": 10.0} for s in stock_codes]
    names = [{"ts_code": s, "name": "SYNTHETIC", "start_date": "2000-01-01", "end_date": None, "ann_date": "2000-01-01"} for s in stock_codes]
    cal = pd.DataFrame({"cal_date": pd.date_range(days[0], days[-1]).strftime("%Y-%m-%d")})
    cal["is_open"] = pd.to_datetime(cal.cal_date).dt.day_of_week.lt(5).astype(int)
    cal["exchange"] = "SSE"
    return DataBundle({"trade_cal": cal, "daily": pd.DataFrame(bars), "stk_limit": pd.DataFrame(limits),
                       "daily_basic": pd.DataFrame(basic), "adj_factor": pd.DataFrame(factors),
                       "index_weight": pd.DataFrame(weights), "namechange": pd.DataFrame(names),
                       "fina_indicator": pd.DataFrame(financials),
                       "stock_basic": pd.DataFrame([{"ts_code": s, "name": "SYNTHETIC", "list_date": "2000-01-01", "delist_date": None} for s in stock_codes]),
                       "index_daily": pd.DataFrame([{"ts_code": "000300.SH", "trade_date": d, "close": 3000 + i} for i, d in enumerate(days)])},
                      {"synthetic": True, "quality": [{"code": "synthetic_dataset", "detail": "Not market data; weekday calendar only"}]})


def make_demo(output):
    root = Path(output).resolve()
    root.mkdir(parents=True, exist_ok=True)
    demo_bundle().save(root / "snapshot")
    (root / "demo.toml").write_text('''[data]
provider = "tinyshare"
snapshot = "snapshot"
strict = false
[backtest]
start = "2026-01-15"
end = "2026-02-10"
initial_capital = 1000000
output = "runs"
[strategy]
factory = "all_weather_rotation"
''')
    return str(root / "demo.toml")
