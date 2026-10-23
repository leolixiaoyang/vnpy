"""Deprecated data preparation entry point."""
from pathlib import Path
from quantlab.cli import main

if __name__ == "__main__":
    config = Path(__file__).resolve().parents[1] / "configs" / "all_weather_rotation.toml"
    raise SystemExit(main(["data", "prepare", "--config", str(config)]))
