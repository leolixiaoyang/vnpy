from datetime import datetime, timedelta
from typing import Protocol

import pandas as pd

from ..quality import DataError, QualityLog
from .normalization import normalize
from .schemas import SCHEMAS, validate_request
from .transports import ProviderError


def tsdate(day):
    return str(day).replace("-", "")


class DataProvider(Protocol):
    def fetch(self, api: str, params: dict, fields=None) -> pd.DataFrame: ...


class TushareProvider:
    def __init__(self, transport=None, cache=None, offline=False, quality=None):
        self.transport, self.cache, self.offline = transport, cache, offline
        self.quality = quality if quality is not None else QualityLog()

    def fetch(self, api, params, fields=None):
        spec = SCHEMAS[api]
        fields = tuple(fields or spec.fields)
        params = {k: tsdate(v) if k.endswith("date") or k == "period" else v for k, v in params.items()}
        validate_request(api, params, fields)
        raw = self.cache.read(api, params, fields) if self.cache else None
        if raw is None:
            if self.offline:
                raise DataError(f"offline cache miss: {api} {params}")
            if self.transport is None:
                raise DataError("An explicit transport is required online")
            raw = self._complete(api, params, fields)
            if self.cache:
                self.cache.write(api, params, fields, raw)
        df = normalize(api, raw)
        if not df.empty and spec.date_axis and "start_date" in params:
            lo = pd.Timestamp(params["start_date"]).strftime("%Y-%m-%d")
            hi = pd.Timestamp(params["end_date"]).strftime("%Y-%m-%d")
            df = df[df[spec.date_axis].between(lo, hi)]
        return df.reset_index(drop=True)

    def optional(self, api, params, fields=None):
        try:
            return self.fetch(api, params, fields)
        except ProviderError as exc:
            self.quality.record("provider_unavailable", f"{api}: {exc.kind}")
            return pd.DataFrame()

    def _complete(self, api, params, fields):
        df = self.transport.query(api, params, fields)
        if not isinstance(df, pd.DataFrame):
            raise DataError(f"{api}: expected DataFrame")
        if len(df) < SCHEMAS[api].cap:
            return df
        if not {"start_date", "end_date"} <= params.keys() or params["start_date"] == params["end_date"]:
            raise DataError(f"{api}: possible truncation at row cap; request a narrower symbol scope")
        lo = datetime.strptime(params["start_date"], "%Y%m%d")
        hi = datetime.strptime(params["end_date"], "%Y%m%d")
        mid = lo + (hi - lo) // 2
        left = self._complete(api, {**params, "end_date": mid.strftime("%Y%m%d")}, fields)
        right = self._complete(api, {**params, "start_date": (mid + timedelta(days=1)).strftime("%Y%m%d")}, fields)
        return pd.concat([left, right], ignore_index=True).drop_duplicates()
