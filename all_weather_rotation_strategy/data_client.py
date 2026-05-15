from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

import pandas as pd
import tinyshare as ts

from config import DATA_PATH, TUSHARE_TOKEN


@dataclass
class TinyshareClient:
    token: str = TUSHARE_TOKEN
    use_cache: bool = True

    def __post_init__(self) -> None:
        if not self.token:
            raise ValueError("未设置 TUSHARE_TOKEN，请先设置环境变量")
        ts.set_token(self.token)
        self.pro = ts.pro_api()
        DATA_PATH.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _as_df(raw: Any) -> pd.DataFrame:
        if raw is None:
            return pd.DataFrame()
        if isinstance(raw, pd.DataFrame):
            return raw.copy()
        if isinstance(raw, list):
            return pd.DataFrame(raw)
        return pd.DataFrame(raw)

    @staticmethod
    def _to_ts_date(day: str | datetime) -> str:
        if isinstance(day, datetime):
            return day.strftime("%Y%m%d")
        return day.replace("-", "")

    @staticmethod
    def _cache_file(prefix: str, **kwargs: str) -> Path:
        key = "_".join(f"{k}-{v}" for k, v in sorted(kwargs.items()))
        safe = key.replace("/", "-").replace(":", "-").replace(",", "-")
        return DATA_PATH / f"{prefix}_{safe}.parquet"

    def _cached_call(self, prefix: str, params: dict[str, str], fn) -> pd.DataFrame:
        cache_file = self._cache_file(prefix, **params)
        if self.use_cache and cache_file.exists():
            return pd.read_parquet(cache_file)

        raw = fn()
        df = self._as_df(raw)
        if self.use_cache and not df.empty:
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            df.to_parquet(cache_file, index=False)
        return df

    def daily(self, ts_code: str, start_date: str, end_date: str, adj: str | None = None) -> pd.DataFrame:
        params = {
            "ts_code": ts_code,
            "start": self._to_ts_date(start_date),
            "end": self._to_ts_date(end_date),
            "adj": str(adj),
        }

        def _call():
            call_kwargs = {
                "ts_code": ts_code,
                "start_date": params["start"],
                "end_date": params["end"],
            }
            if adj:
                call_kwargs["adj"] = adj
            if ts_code.startswith("51") or ts_code.startswith("15"):
                return self.pro.fund_daily(**call_kwargs)
            return self.pro.daily(**call_kwargs)

        df = self._cached_call("daily", params, _call)
        if not df.empty and "trade_date" in df.columns:
            df["trade_date"] = df["trade_date"].astype(str)
            df = df.sort_values("trade_date").reset_index(drop=True)
        return df

    def daily_basic(self, ts_codes: list[str], trade_date: str) -> pd.DataFrame:
        date_text = self._to_ts_date(trade_date)
        chunks = [ts_codes[i: i + 100] for i in range(0, len(ts_codes), 100)]
        frames: list[pd.DataFrame] = []

        for chunk in chunks:
            code_text = ",".join(chunk)
            params = {"code": code_text, "date": date_text}

            def _call():
                return self.pro.daily_basic(
                    ts_code=code_text,
                    trade_date=date_text,
                    fields=(
                        "ts_code,trade_date,close,turnover_rate,pe,pb,ps,eps,"
                        "total_mv,circ_mv"
                    ),
                )

            df = self._cached_call("daily_basic", params, _call)
            if not df.empty:
                frames.append(df)

        if not frames:
            return pd.DataFrame()
        out = pd.concat(frames, ignore_index=True)
        out["trade_date"] = out["trade_date"].astype(str)
        return out.drop_duplicates(subset=["ts_code", "trade_date"])

    def stock_basic(self) -> pd.DataFrame:
        params = {"status": "L"}

        def _call():
            return self.pro.stock_basic(
                list_status="L",
                fields="ts_code,name,list_date,market",
            )

        df = self._cached_call("stock_basic", params, _call)
        if not df.empty and "list_date" in df.columns:
            df["list_date"] = df["list_date"].astype(str)
        return df

    def index_constituents(self, index_code: str, trade_date: str) -> list[str]:
        end = datetime.strptime(self._to_ts_date(trade_date), "%Y%m%d")
        start = (end - timedelta(days=40)).strftime("%Y%m%d")
        end_text = end.strftime("%Y%m%d")

        params = {"index": index_code, "start": start, "end": end_text}

        def _call():
            return self.pro.index_weight(
                index_code=index_code,
                start_date=start,
                end_date=end_text,
            )

        df = self._cached_call("index_weight", params, _call)
        if df.empty or "con_code" not in df.columns:
            return []

        df["trade_date"] = df["trade_date"].astype(str)
        latest_date = df["trade_date"].max()
        latest = df[df["trade_date"] == latest_date]
        return sorted(latest["con_code"].dropna().unique().tolist())

    def latest_fina_indicator(self, ts_code: str, trade_date: str) -> dict[str, float]:
        end = self._to_ts_date(trade_date)
        start = (datetime.strptime(end, "%Y%m%d") - timedelta(days=1200)).strftime("%Y%m%d")
        params = {"code": ts_code, "start": start, "end": end}

        def _call():
            return self.pro.fina_indicator(
                ts_code=ts_code,
                start_date=start,
                end_date=end,
                fields=(
                    "ts_code,end_date,roe,roa,roic,netprofit_margin,"
                    "grossprofit_margin,or_yoy,debt_to_assets"
                ),
            )

        df = self._cached_call("fina_indicator", params, _call)
        if df.empty:
            return {}
        df["end_date"] = df["end_date"].astype(str)
        df = df[df["end_date"] <= end]
        if df.empty:
            return {}
        row = df.sort_values("end_date").iloc[-1]
        return {k: row[k] for k in df.columns if k not in {"ts_code", "end_date"}}

    def latest_income(self, ts_code: str, trade_date: str) -> dict[str, float]:
        end = self._to_ts_date(trade_date)
        start = (datetime.strptime(end, "%Y%m%d") - timedelta(days=1200)).strftime("%Y%m%d")
        params = {"code": ts_code, "start": start, "end": end}

        def _call():
            return self.pro.income(
                ts_code=ts_code,
                start_date=start,
                end_date=end,
                fields=(
                    "ts_code,end_date,revenue,oper_cost,total_profit,"
                    "n_income,non_oper_income,non_oper_exp,admin_exp"
                ),
            )

        df = self._cached_call("income", params, _call)
        if df.empty:
            return {}
        df["end_date"] = df["end_date"].astype(str)
        df = df[df["end_date"] <= end]
        if df.empty:
            return {}
        row = df.sort_values("end_date").iloc[-1]
        return {k: row[k] for k in df.columns if k not in {"ts_code", "end_date"}}

    def latest_balance(self, ts_code: str, trade_date: str) -> dict[str, float]:
        end = self._to_ts_date(trade_date)
        start = (datetime.strptime(end, "%Y%m%d") - timedelta(days=1200)).strftime("%Y%m%d")
        params = {"code": ts_code, "start": start, "end": end}

        def _call():
            return self.pro.balancesheet(
                ts_code=ts_code,
                start_date=start,
                end_date=end,
                fields="ts_code,end_date,total_assets,total_liab,undistr_porfit,inventories,total_share",
            )

        df = self._cached_call("balancesheet", params, _call)
        if df.empty:
            return {}
        df["end_date"] = df["end_date"].astype(str)
        df = df[df["end_date"] <= end]
        if df.empty:
            return {}
        row = df.sort_values("end_date").iloc[-1]
        return {k: row[k] for k in df.columns if k not in {"ts_code", "end_date"}}

    def latest_cashflow(self, ts_code: str, trade_date: str) -> dict[str, float]:
        end = self._to_ts_date(trade_date)
        start = (datetime.strptime(end, "%Y%m%d") - timedelta(days=1200)).strftime("%Y%m%d")
        params = {"code": ts_code, "start": start, "end": end}

        def _call():
            return self.pro.cashflow(
                ts_code=ts_code,
                start_date=start,
                end_date=end,
                fields="ts_code,end_date,n_cashflow_act,ncfps",
            )

        df = self._cached_call("cashflow", params, _call)
        if df.empty:
            return {}
        df["end_date"] = df["end_date"].astype(str)
        df = df[df["end_date"] <= end]
        if df.empty:
            return {}
        row = df.sort_values("end_date").iloc[-1]
        return {k: row[k] for k in df.columns if k not in {"ts_code", "end_date"}}

    def close_on_date(self, ts_codes: Iterable[str], trade_date: str) -> pd.DataFrame:
        date_text = self._to_ts_date(trade_date)
        rows: list[pd.DataFrame] = []
        for code in ts_codes:
            daily_df = self.daily(
                ts_code=code,
                start_date=(datetime.strptime(date_text, "%Y%m%d") - timedelta(days=40)).strftime("%Y%m%d"),
                end_date=date_text,
                adj=None,
            )
            if daily_df.empty:
                continue
            day_df = daily_df[daily_df["trade_date"] == date_text]
            if day_df.empty:
                continue
            rows.append(day_df.iloc[[-1]])
        if not rows:
            return pd.DataFrame()
        return pd.concat(rows, ignore_index=True)
