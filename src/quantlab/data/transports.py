"""Optional SDKs are imported only after explicit provider selection."""
import importlib
import os
import time
from typing import Protocol

import pandas as pd

from ..quality import DataError
from .schemas import validate_request


class ProviderError(RuntimeError):
    def __init__(self, kind: str, api: str):
        # Providers can echo credentials in exceptions: never retain that text.
        self.kind, self.api = kind, api
        super().__init__(f"{api}: {kind}")


class Transport(Protocol):
    def query(self, api_name: str, params: dict, fields: tuple[str, ...]) -> pd.DataFrame: ...


class SDKTransport:
    def __init__(self, provider="tinyshare", client=None, token=None, retries=2, delay=1.0):
        if provider not in {"tinyshare", "tushare"}:
            raise DataError("Choose tinyshare or tushare explicitly")
        self.provider, self.retries, self.delay = provider, retries, delay
        self.version = "injected"
        if client is None:
            try:
                sdk = importlib.import_module(provider)
            except ImportError:
                raise ProviderError("sdk_not_installed", provider) from None
            credential = token or os.getenv("TINYSHARE_TOKEN" if provider == "tinyshare" else "TUSHARE_TOKEN")
            if not credential:
                raise ProviderError("credential_missing", provider)
            try:
                client = sdk.pro_api(credential)
            except Exception:
                raise ProviderError("initialization_failed", provider) from None
            self.version = str(getattr(sdk, "__version__", "unknown"))
        self.client = client

    def query(self, api_name, params, fields):
        validate_request(api_name, params, fields)
        for attempt in range(self.retries + 1):
            try:
                result = self.client.query(api_name, fields=",".join(fields), **params)
                if not isinstance(result, pd.DataFrame):
                    raise DataError(f"{api_name}: SDK must return pandas.DataFrame")
                missing = set(fields) - set(result.columns)
                if missing and not result.empty:
                    raise DataError(f"{api_name}: requested columns missing: {sorted(missing)}")
                return result.reindex(columns=fields).copy() if result.empty else result.copy()
            except DataError:
                raise
            except Exception as exc:
                msg = str(exc).lower()
                kind = "provider_error"
                if any(w in msg for w in ["权限", "积分", "permission", "2002", "token"]):
                    kind = "permission_or_auth"
                elif any(w in msg for w in ["频率", "每分钟", "rate limit", "too many"]):
                    kind = "rate_limit"
                elif isinstance(exc, (TimeoutError, ConnectionError)) or any(w in msg for w in ["timeout", "timed out", "connection"]):
                    kind = "temporary_network"
                elif any(w in msg for w in ["参数", "字段", "parameter", "field"]):
                    raise DataError(f"{api_name}: provider rejected request contract") from None
                if kind in {"rate_limit", "temporary_network"} and attempt < self.retries:
                    time.sleep(self.delay * 2 ** attempt)
                    continue
                raise ProviderError(kind, api_name) from None
