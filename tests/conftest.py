import pytest

from quantlab.data.view import MarketDataView
from quantlab.demo import demo_bundle


@pytest.fixture
def bundle():
    return demo_bundle()


@pytest.fixture
def market(bundle):
    return MarketDataView(bundle, "2026-02-02")
