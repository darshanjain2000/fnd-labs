from __future__ import annotations

import pandas as pd

from core.logging import get_logger
from strategies import ALL_STRATEGIES, Signal
from strategies.base import Strategy

log = get_logger(__name__)


class SignalAgent:
    def __init__(self, strategies: list[Strategy] | None = None) -> None:
        self.strategies: list[Strategy] = strategies or [s() for s in ALL_STRATEGIES]

    def generate(self, symbol: str, candles: pd.DataFrame) -> list[Signal]:
        signals: list[Signal] = []
        for strat in self.strategies:
            try:
                sig = strat.evaluate(symbol, candles)
            except Exception as e:
                log.warning("strategy_error", strategy=strat.name, error=str(e))
                continue
            if sig is not None:
                signals.append(sig)
        return signals
