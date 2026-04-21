from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Literal

import pandas as pd

# All regimes recognised by detect_regime()
Regime = Literal["trend_up", "trend_down", "range", "high_vol"]


@dataclass
class Signal:
    """A trade setup produced by a strategy.

    Attributes:
        symbol: NSE trading symbol (e.g. "NIFTY").
        strategy: Name of the strategy that generated this signal.
        side: "BUY" or "SELL".
        entry: Suggested entry price.
        stop_loss: Hard stop-loss price.
        target: Optional profit target price.
        confidence: Strategy confidence in [0, 1].
        context: Free-form dict of diagnostic values (e.g. indicator readings).
    """

    symbol: str
    strategy: str
    side: Literal["BUY", "SELL"]
    entry: float
    stop_loss: float
    target: float | None = None
    confidence: float = 0.5
    context: dict = field(default_factory=dict)


class Strategy(ABC):
    """Abstract base for all trading strategies.

    Subclasses must set ``name`` and implement ``evaluate()``.
    Optionally override ``preferred_regimes`` to restrict which market
    regimes the strategy runs in (used by ``SignalAgent`` for regime filtering).
    """

    name: str = "base"
    preferred_regimes: tuple[Regime, ...] = ("trend_up", "trend_down", "range", "high_vol")

    @abstractmethod
    def evaluate(self, symbol: str, candles: pd.DataFrame) -> Signal | None:
        """Return a Signal if setup triggers, else None.

        Args:
            symbol: NSE trading symbol (e.g. "NIFTY").
            candles: OHLCV DataFrame with pre-computed indicators.

        Returns:
            A Signal if a setup fires, None otherwise. Must never raise.
        """

    def applies_to_regime(self, regime: str) -> bool:
        """Return True if this strategy should run in *regime*.

        Args:
            regime: Current market regime string (from detect_regime()).

        Returns:
            True if the strategy is valid for the given regime.
        """
        return regime in self.preferred_regimes
