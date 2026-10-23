"""Independent research core. Importing it never imports a market-data SDK."""
__version__ = "0.3.0"

from .models import BuyValue, Keep, TargetValue

__all__ = ["BuyValue", "Keep", "TargetValue", "__version__"]
