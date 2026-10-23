import pandas as pd

from ..quality import DataError
from .schemas import SCHEMAS

VERSION = "tushare-v1"
TEXT = {"ts_code", "con_code", "index_code", "name", "market", "exchange", "list_status", "publisher",
        "status", "fund_type", "report_type", "comp_type", "update_flag", "div_proc", "change_reason"}


def normalize(api: str, raw: pd.DataFrame) -> pd.DataFrame:
    spec = SCHEMAS[api]
    if raw.empty:
        return raw.copy()
    missing = set(spec.required) - set(raw.columns)
    if missing:
        raise DataError(f"{api}: required columns missing {sorted(missing)}")
    df = raw.copy()
    for col in df.columns:
        if col.endswith("date") or col == "imp_anndate":
            text = df[col].astype("string").str.replace(r"\.0$", "", regex=True)
            df[col] = pd.to_datetime(text, errors="coerce").dt.strftime("%Y-%m-%d")
        elif col not in TEXT:
            values = pd.to_numeric(df[col], errors="coerce")
            if (df[col].notna() & values.isna()).any():
                raise DataError(f"{api}.{col}: invalid numeric values")
            df[col] = values
    for col in spec.required:
        if df[col].isna().any():
            raise DataError(f"{api}.{col}: null required value")
    # Endpoint-specific units; balance sheet shares already are individual shares.
    if api == "daily_basic":
        for col in ["total_mv", "circ_mv", "total_share", "float_share", "free_share"]:
            if col in df:
                df[col] *= 10000
    if api in {"daily", "fund_daily", "index_daily"}:
        if "vol" in df:
            df["volume"] = df.pop("vol") * 100
        if "amount" in df:
            df["amount"] *= 1000
    keys = [k for k in spec.keys if k in df]
    if keys:
        # Identical duplicates are harmless; contradictory historical versions aren't.
        df = df.drop_duplicates()
        if df.duplicated(keys).any():
            raise DataError(f"{api}: conflicting duplicate records for {keys}")
        df = df.sort_values(keys, kind="stable")
    return df.reset_index(drop=True)
