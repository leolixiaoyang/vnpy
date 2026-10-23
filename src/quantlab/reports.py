import hashlib
import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from . import __version__


def summary(equity, initial, benchmark=None):
    if equity.empty:
        return {}
    values = np.r_[initial, equity.equity.to_numpy(dtype=float)]
    returns = values[1:] / values[:-1] - 1
    drawdown = values / np.maximum.accumulate(values) - 1
    n, ratio = len(returns), values[-1] / initial
    std = float(np.std(returns, ddof=1)) if n > 1 else 0.0
    out = {"initial_capital": initial, "final_equity": float(values[-1]), "trading_days": n,
           "total_return": float(ratio - 1), "annual_return": float(ratio ** (252 / n) - 1) if ratio > 0 else -1.0,
           "max_drawdown": float(np.min(drawdown)), "volatility": std * np.sqrt(252),
           "sharpe": float(np.mean(returns) / std * np.sqrt(252)) if std else 0.0}
    if benchmark is not None and not benchmark.empty and benchmark.close.notna().all():
        out["benchmark_return"] = float(benchmark.close.iloc[-1] / benchmark.close.iloc[0] - 1)
        out["excess_return"] = out["total_return"] - out["benchmark_return"]
    return out


def json_value(value):
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, Path):
        return str(value)
    raise TypeError(type(value).__name__)


@dataclass
class BacktestResult:
    equity: pd.DataFrame
    orders: pd.DataFrame
    positions: pd.DataFrame
    benchmark: pd.DataFrame
    initial_capital: float
    metadata: dict = field(default_factory=dict)

    @property
    def trades(self):
        if self.orders.empty:
            return self.orders.copy()
        df = self.orders[self.orders.status == "filled"].copy()
        # Preserve legacy export names as aliases, without preserving broken accounting.
        df["trade_date"], df["ts_code"], df["action"] = df.date, df.symbol, df.side
        df["volume"], df["fee"], df["turnover"] = df.quantity, df.fee_cents / 100, df.turnover_cents / 100
        return df

    @property
    def statistics(self):
        return summary(self.equity, self.initial_capital, self.benchmark)

    def export(self, root, config=None, plot=False):
        config = config or {}
        fingerprint = hashlib.sha256(json.dumps([config, self.metadata], sort_keys=True, default=json_value).encode()).hexdigest()[:12]
        root = Path(root)
        root.mkdir(parents=True, exist_ok=True)
        directory = root / fingerprint
        index = 1
        while directory.exists():
            directory = root / f"{fingerprint}-{index}"
            index += 1
        directory.mkdir()
        self.equity.to_csv(directory / "all_weather_equity.csv", index=False)
        self.trades.to_csv(directory / "all_weather_trades.csv", index=False)
        self.orders.to_csv(directory / "orders.csv", index=False)
        self.positions.to_csv(directory / "positions.csv", index=False)
        self.benchmark.to_csv(directory / "benchmark.csv", index=False)
        pd.DataFrame([self.statistics]).to_csv(directory / "all_weather_summary.csv", index=False)
        package = Path(__file__).resolve().parent
        source_hash = hashlib.sha256()
        for file in sorted(package.rglob("*.py")):
            source_hash.update(str(file.relative_to(package)).encode())
            source_hash.update(file.read_bytes())
        try:
            commit = subprocess.run(["git", "-C", str(package), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
            dirty = bool(subprocess.run(["git", "-C", str(package), "status", "--porcelain"], capture_output=True, text=True, check=True).stdout)
        except (OSError, subprocess.CalledProcessError):
            commit, dirty = None, None
        record = {"quantlab_version": __version__, "package_source_sha256": source_hash.hexdigest(), "git_commit": commit, "git_dirty": dirty,
                  "config": config, "statistics": self.statistics, **self.metadata}
        (directory / "experiment.json").write_text(json.dumps(record, indent=2, ensure_ascii=False, default=json_value))
        (directory / "trade_intents.csv").write_text(self.orders.to_csv(index=False))
        if plot:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            fig, ax = plt.subplots()
            ax.plot(self.equity.trade_date, self.equity.equity / self.initial_capital, label="strategy")
            if not self.benchmark.empty and self.benchmark.close.notna().all():
                ax.plot(self.benchmark.trade_date, self.benchmark.close / self.benchmark.close.iloc[0], label=self.metadata.get("benchmark"))
            ax.legend()
            ax.tick_params(axis="x", labelrotation=60)
            fig.tight_layout()
            fig.savefig(directory / "equity.png")
            plt.close(fig)
        return directory
