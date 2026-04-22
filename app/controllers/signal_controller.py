"""Controller for strategy signal generation."""
from __future__ import annotations

import pandas as pd

from app.services.signal_service import SignalService
from app.strategies.base import Signal


class SignalController:
    """Thin wrapper over :class:`SignalService`."""

    def __init__(self, service: SignalService | None = None) -> None:
        """Initialise the controller.

        Args:
            service: Injected service. Defaults to a new :class:`SignalService`.
        """
        self._service = service or SignalService()

    def generate(
        self,
        symbol: str,
        candles: pd.DataFrame,
        htf_candles: pd.DataFrame | None = None,
    ) -> list[Signal]:
        """Delegate to :meth:`SignalService.generate`."""
        return self._service.generate(symbol, candles, htf_candles)
