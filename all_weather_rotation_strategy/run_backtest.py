"""Deprecated: use quantlab backtest --config ... --offline."""
import sys
import warnings
from pathlib import Path
from quantlab.cli import main

def run():
    warnings.warn("Use quantlab backtest; the legacy engine has been replaced", DeprecationWarning, stacklevel=2)
    config = Path(__file__).resolve().parents[1] / "configs" / "all_weather_rotation.toml"
    return main(["backtest", "--config", str(config), "--offline", *sys.argv[1:]])

if __name__ == "__main__":
    raise SystemExit(run())
