import hashlib
import json
from pathlib import Path

import pandas as pd

from .normalization import VERSION


class QueryCache:
    """Raw response cache. Covering date ranges satisfy narrower requests."""
    def __init__(self, path, identity="tinyshare"):
        self.path = Path(path)
        self.identity = identity

    def _base(self, api, params, fields):
        key = {k: v for k, v in params.items() if k not in {"start_date", "end_date"}}
        blob = json.dumps([self.identity, VERSION, api, key, sorted(fields)], sort_keys=True)
        return hashlib.sha256(blob.encode()).hexdigest()

    def read(self, api, params, fields):
        base = self._base(api, params, fields)
        for meta_path in sorted(self.path.glob(f"{base}-*.json")):
            meta = json.loads(meta_path.read_text())
            lo, hi = params.get("start_date", ""), params.get("end_date", "")
            if meta["start"] <= lo and meta["end"] >= hi:
                return pd.read_parquet(meta_path.with_suffix(".parquet"))
        return None

    def write(self, api, params, fields, df):
        self.path.mkdir(parents=True, exist_ok=True)
        lo, hi = params.get("start_date", ""), params.get("end_date", "")
        stem = self.path / f"{self._base(api, params, fields)}-{lo}-{hi}"
        df.to_parquet(stem.with_suffix(".parquet"), index=False)
        stem.with_suffix(".json").write_text(json.dumps({"start": lo, "end": hi, "rows": len(df)}))
