"""Compatibility alias for the independent implementation."""
from quantlab.strategies.all_weather_rotation import AllWeatherRotation
from quantlab.backtest import BacktestRunner

class AllWeatherRotationBacktester:
    def __init__(self, bundle, start_date, end_date, initial_capital=1_000_000, **kwargs):
        self.runner = BacktestRunner(bundle, AllWeatherRotation(), initial_capital, **kwargs)
        self.start_date, self.end_date = start_date, end_date

    def run(self):
        result = self.runner.run(self.start_date, self.end_date)
        return result.trades, result.equity
