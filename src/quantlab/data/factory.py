"""Explicit data-source selection. SDKs remain optional and lazily imported."""
from ..quality import DataError, QualityLog
from .cache import QueryCache
from .provider import TushareProvider
from .transports import SDKTransport

PROVIDERS = ("akshare", "tushare", "tinyshare")
DEFAULT_PROVIDER = "akshare"


def transport_for(provider, config=None, quality=None):
    if provider not in PROVIDERS:
        raise DataError(f"data.provider must be one of {', '.join(PROVIDERS)}")
    if provider == "akshare":
        from .akshare import AKShareTransport
        config = config or {}
        period = config.get("backtest", {})
        options = config.get("data", {}).get("akshare", {})
        return AKShareTransport(quality=quality, start=period.get("start", "2018-01-01"),
                                end=period.get("end", "2026-04-30"),
                                lof_symbols=options.get("lof_symbols", ["164824.SZ"]))
    return SDKTransport(provider)


def provider_for(config):
    data = config["data"]
    quality = QualityLog(data.get("strict", False))
    transport = transport_for(data.get("provider", DEFAULT_PROVIDER), config, quality)
    # Mapping and options affect raw responses as well as the SDK's own version.
    identity = f"{transport.provider}:{transport.version}:{getattr(transport, 'mapping_version', 'sdk')}"
    if transport.provider == "akshare":
        import json
        identity += ":" + json.dumps({"period": {k: config["backtest"][k] for k in ["start", "end"]},
                                    "options": data.get("akshare", {})}, sort_keys=True)
    return TushareProvider(transport, QueryCache(data.get("cache", ".quantlab/cache"), identity), quality=quality)
