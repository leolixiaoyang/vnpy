import ast
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pandas as pd
import pytest

from quantlab.cli import main
from quantlab.data.bundle import DataBundle
from quantlab.demo import make_demo
from quantlab.reports import summary


def test_first_day_cost_and_compound_statistics():
    stats = summary(pd.DataFrame({"equity": [90., 99.]}), 100)
    assert stats["max_drawdown"] == pytest.approx(-.1)
    assert stats["total_return"] == pytest.approx(-.01)
    assert stats["annual_return"] == pytest.approx(.99 ** 126 - 1)


def test_offline_cli_exports_and_config_not_modified(tmp_path, capsys):
    config = Path(make_demo(tmp_path))
    text = config.read_bytes()
    assert main(["backtest", "--config", str(config), "--offline"]) == 0
    report = json.loads(capsys.readouterr().out)
    directory = Path(report["output"])
    experiment = json.loads((directory / "experiment.json").read_text())
    assert "same_day_close" in experiment["execution_model"]
    assert experiment["data"]["snapshot_id"]
    assert experiment["quality"]
    assert config.read_bytes() == text
    assert (directory / "orders.csv").exists()


def test_doctor_without_sdk_or_credentials(capsys, monkeypatch):
    monkeypatch.delenv("TINYSHARE_TOKEN", raising=False)
    assert main(["doctor", "--provider", "tinyshare"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert not report["credential_configured"] and not report["online_verified"]


def test_no_framework_or_sdk_runtime_imports():
    root = Path(__file__).resolve().parents[1] / "src" / "quantlab"
    banned = {"vnpy", "jqdata", "jqfactor", "jqdatasdk", "tinyshare", "tushare", "akshare"}
    for file in root.rglob("*.py"):
        tree = ast.parse(file.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert not any(n.name.split(".")[0] in banned for n in node.names)
            if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                assert node.module.split(".")[0] not in banned


def test_clean_import_never_loads_sdks():
    script = "import quantlab; from quantlab.backtest import BacktestRunner; import sys; assert not {'vnpy','jqdata','tinyshare','tushare','akshare'} & sys.modules.keys()"
    subprocess.run([sys.executable, "-c", script], check=True)
