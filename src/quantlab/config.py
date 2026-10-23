from pathlib import Path
import tomllib

from .quality import DataError


def load_config(path):
    path = Path(path).resolve()
    with path.open("rb") as handle:
        config = tomllib.load(handle)
    if not {"backtest", "data"} <= config.keys():
        raise DataError("Config requires [backtest] and [data]")
    from .data.factory import DEFAULT_PROVIDER, PROVIDERS
    config["data"].setdefault("provider", DEFAULT_PROVIDER)
    if config["data"]["provider"] not in PROVIDERS:
        raise DataError(f"data.provider must be one of {', '.join(PROVIDERS)}")
    for key in ["start", "end"]:
        from datetime import date
        value = config["backtest"][key]
        config["backtest"][key] = date.fromisoformat(str(value)).isoformat()
    if config["backtest"]["start"] > config["backtest"]["end"]:
        raise DataError("start must not follow end")
    for section, names in [("data", ["snapshot", "cache"]), ("backtest", ["output"])]:
        for name in names:
            value = config[section].get(name)
            if value is not None:
                config[section][name] = str((path.parent / value).resolve())
    return config
