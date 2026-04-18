from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Literal

import pandas as pd


@dataclass
class Signal:
    symbol: str
    strategy: str
    side: Literal["BUY", "SELL"]
    entry: float
    stop_loss: float
    target: float | None = None
    confidence: float = 0.5
    context: dict = field(default_factory=dict)


class Strategy(ABC):
    name: str = "base"

    @abstractmethod
    def evaluate(self, symbol: str, candles: pd.DataFrame) -> Signal | None:
        """Return a Signal if setup triggers, else None. `candles` must include indicators."""
