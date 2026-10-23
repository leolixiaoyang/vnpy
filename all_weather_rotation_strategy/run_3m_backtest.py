"""Compatibility wrapper: dates now belong in the explicit TOML configuration."""
from all_weather_rotation_strategy.run_backtest import run

if __name__ == "__main__":
    raise SystemExit(run())
