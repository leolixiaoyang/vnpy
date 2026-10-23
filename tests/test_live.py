"""Opt-in only; no credentials needed for AKShare, separate tokens for others."""
import os

import pytest

from quantlab.cli import doctor
from quantlab.config import load_config


@pytest.mark.live
@pytest.mark.skipif(os.getenv("QUANTLAB_LIVE") != "1", reason="Set QUANTLAB_LIVE=1 for explicit network probes")
def test_selected_sdk_contracts():
    provider = os.environ.get("QUANTLAB_PROVIDER", "akshare")
    config = load_config(os.environ.get("QUANTLAB_CONFIG", "configs/all_weather_rotation.toml"))
    report = doctor(provider, config, probe=True)
    assert report["online_verified"], report["endpoints"]
