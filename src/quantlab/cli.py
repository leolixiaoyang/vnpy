import argparse
import importlib
import json
import os
import sys

import pandas as pd

from .backtest import BacktestRunner
from .broker import FeeModel
from .config import load_config
from .data.bundle import DataBundle
from .data.factory import DEFAULT_PROVIDER, PROVIDERS, provider_for, transport_for
from .data.prepare import prepare
from .data.provider import TushareProvider
from .data.transports import ProviderError
from .quality import DataError
from .strategies.all_weather_rotation import AllWeatherRotation


def strategy_factory(config):
    settings = config.get("strategy", {})
    factory = settings.get("factory", "all_weather_rotation")
    if factory == "all_weather_rotation":
        cls = AllWeatherRotation
    else:
        module, name = factory.split(":", 1)
        cls = getattr(importlib.import_module(module), name)
    return cls(**settings.get("parameters", {}))


def run_config(config, offline=False, plot=False):
    # Explicit preparation is the only path that opens a network connection.
    bundle = DataBundle.load(config["data"]["snapshot"])
    backtest = config["backtest"]
    runner = BacktestRunner(bundle, strategy_factory(config), backtest.get("initial_capital", 1_000_000),
        FeeModel(**config.get("fees", {})), config["data"].get("strict", False),
        config.get("instruments", {}), config.get("fallback_pools", {}), backtest.get("benchmark", "000300.SH"))
    result = runner.run(backtest["start"], backtest["end"])
    path = result.export(backtest.get("output", "runs"), config, plot)
    return result, path


def doctor(provider, config=None, probe=False):
    import importlib.util
    from importlib.metadata import version, PackageNotFoundError
    installed = importlib.util.find_spec(provider) is not None
    try:
        sdk_version = version(provider) if installed else None
    except PackageNotFoundError:
        sdk_version = "unknown"
    env = {"tinyshare": "TINYSHARE_TOKEN", "tushare": "TUSHARE_TOKEN", "akshare": None}[provider]
    report = {"provider": provider, "sdk_installed": installed, "sdk_version": sdk_version,
              "credentials_required": env is not None,
              "credential_configured": bool(os.getenv(env)) if env else None, "credential_env": env,
              "online_verified": False, "endpoints": {}}
    if provider == "akshare":
        report["coverage_limits"] = ["historical_constituents", "historical_st", "historical_price_limits",
                                     "delisted_stock_metadata", "financial_revisions", "fund_corporate_actions"]
    if not probe:
        return report
    if not config:
        raise DataError("doctor --probe requires --config")
    transport = transport_for(provider, config)
    client = TushareProvider(transport, quality=getattr(transport, "quality", None))
    day = config["backtest"]["end"]
    funds = config.get("strategy", {}).get("parameters", {}).get("funds", list(AllWeatherRotation().params.funds))
    calls = [("trade_cal", {"exchange": "SSE", "start_date": day, "end_date": day}),
             ("daily", {"ts_code": "000001.SZ", "start_date": day, "end_date": day}),
             ("index_daily", {"ts_code": "000300.SH", "start_date": day, "end_date": day}),
             ("daily_basic", {"ts_code": "000001.SZ", "trade_date": day}),
             ("fina_indicator", {"ts_code": "000001.SZ", "start_date": "20250101", "end_date": day}),
             ("income", {"ts_code": "000001.SZ", "start_date": "20250101", "end_date": day}),
             ("balancesheet", {"ts_code": "000001.SZ", "start_date": "20250101", "end_date": day}),
             ("cashflow", {"ts_code": "000001.SZ", "start_date": "20250101", "end_date": day}),
             ("stk_limit", {"ts_code": "000001.SZ", "trade_date": day})]
    calls.extend(("fund_daily", {"ts_code": s, "start_date": "20260101", "end_date": day}) for s in funds)
    if provider == "akshare":
        calls.extend([("stock_basic", {"ts_code": "000001.SZ", "list_status": "L"}),
                      ("index_weight", {"index_code": "000300.SH", "start_date": "20100101", "end_date": day}),
                      ("index_weight", {"index_code": "399101.SZ", "start_date": "20100101", "end_date": day}),
                      ("namechange", {"ts_code": "000001.SZ", "start_date": "20100101", "end_date": day})])
    sample_tables = {}
    for api, params in calls:
        label = f"{api}:{params.get('ts_code', '')}"
        if "index_code" in params:
            label += params["index_code"]
        if api in getattr(transport, "unsupported", set()):
            report["endpoints"][label] = {"status": "unsupported"}
            continue
        try:
            frame = client.fetch(api, params)
            report["endpoints"][label] = {"status": "verified" if not frame.empty else "empty_unverified", "rows": len(frame), "columns": list(frame)}
            sample_tables[label.replace(":", "_").replace(".", "_")] = frame.head(5)
        except ProviderError as exc:
            report["endpoints"][label] = {"status": exc.kind}
        except DataError:
            report["endpoints"][label] = {"status": "contract_failed"}
    report["online_verified"] = all(v["status"] in {"verified", "unsupported"} for v in report["endpoints"].values())
    report["full_strategy_coverage_verified"] = False  # A small probe cannot establish historical coverage.
    report["quality"] = client.quality.export()
    sample = config["data"]["snapshot"] + "-contract-samples"
    DataBundle(sample_tables, report).save(sample)
    report["sample_snapshot"] = sample
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(prog="quantlab")
    sub = parser.add_subparsers(dest="command", required=True)
    diag = sub.add_parser("doctor")
    diag.add_argument("--provider", choices=PROVIDERS, help="Override data.provider (default: akshare)")
    diag.add_argument("--config")
    diag.add_argument("--probe", action="store_true")
    data = sub.add_parser("data")
    datasub = data.add_subparsers(dest="action", required=True)
    prep = datasub.add_parser("prepare")
    prep.add_argument("--config", required=True)
    prep.add_argument("--provider", choices=PROVIDERS, help="Override data.provider for this preparation")
    run = sub.add_parser("backtest")
    run.add_argument("--config", required=True)
    run.add_argument("--offline", action="store_true", help="Backtests always use only the frozen snapshot")
    run.add_argument("--plot", action="store_true")
    demo = sub.add_parser("demo")
    demo.add_argument("--output", default="demo-data")
    args = parser.parse_args(argv)
    try:
        if args.command == "doctor":
            config = load_config(args.config) if args.config else None
            selected = args.provider or (config["data"]["provider"] if config else DEFAULT_PROVIDER)
            report = doctor(selected, config, args.probe)
            print(json.dumps(report, indent=2))
            return 0 if not args.probe or report["online_verified"] else 1
        if args.command == "demo":
            from .demo import make_demo
            print(make_demo(args.output))
            return 0
        config = load_config(args.config)
        if args.command == "data":
            if args.provider:
                config["data"]["provider"] = args.provider
            bundle = prepare(provider_for(config), config)
            manifest = bundle.save(config["data"]["snapshot"])
            print(json.dumps({"snapshot": config["data"]["snapshot"], "id": manifest["snapshot_id"], "quality_events": len(bundle.metadata.get("quality", []))}))
        else:
            result, path = run_config(config, args.offline, args.plot)
            print(json.dumps({"output": str(path), "statistics": result.statistics, "quality_events": len(result.metadata["quality"])}))
        return 0
    except (DataError, ProviderError, OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
