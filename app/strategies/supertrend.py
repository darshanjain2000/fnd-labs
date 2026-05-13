"""Supertrend crossover strategy.

Fires on a direction flip of the Supertrend indicator — a trend-following
signal that uses ATR-based bands to define dynamic support/resistance.
"""

from __future__ import annotations

import pandas as pd

from app.strategies.base import Signal, Strategy


class SupertrendStrategy(Strategy):
    """Go long/short on a Supertrend direction flip.

    Preferred regimes: trend_up, trend_down (momentum environment).
    Stop-loss is placed at the Supertrend line itself; target is a 2× ATR extension.
    """

    name = "supertrend"
    preferred_regimes = ("trend_up", "trend_down")

    def __init__(self, atr_mult: float = 3.0, period: int = 10) -> None:
        """Initialise strategy parameters.

        Args:
            atr_mult: ATR multiplier used in the Supertrend band (default 3.0).
            period: ATR lookback period (default 10).
        """
        self.atr_mult = atr_mult
        self.period = period

    def evaluate(self, symbol: str, candles: pd.DataFrame) -> Signal | None:
        """Fire on a Supertrend direction crossover.

        Args:
            symbol: NSE trading symbol.
            candles: OHLCV DataFrame with supertrend, supertrend_dir, atr14 columns.

        Returns:
            Signal on direction flip; None otherwise.
        """
        if len(candles) < self.period + 2:
            return None
        last = candles.iloc[-1]
        prev = candles.iloc[-2]

        dir_now = float(last.get("supertrend_dir", float("nan")))
        dir_prev = float(prev.get("supertrend_dir", float("nan")))
        atr = float(last.get("atr14", float("nan")))
        close = float(last["close"])
        st_line = float(last.get("supertrend", float("nan")))

        if any(pd.isna(v) for v in (dir_now, dir_prev, atr, st_line)):
            return None

        risk = abs(close - st_line)
        if risk <= 0:
            return None

        # Bearish → bullish flip
        if dir_prev == -1.0 and dir_now == 1.0:
            return Signal(
                symbol=symbol,
                strategy=self.name,
                side="BUY",
                entry=close,
                stop_loss=round(st_line, 2),
                target=round(close + 2 * risk, 2),
                confidence=0.65,
                context={"supertrend": st_line, "dir": int(dir_now), "atr": atr},
            )
        # Bullish → bearish flip
        if dir_prev == 1.0 and dir_now == -1.0:
            return Signal(
                symbol=symbol,
                strategy=self.name,
                side="SELL",
                entry=close,
                stop_loss=round(st_line, 2),
                target=round(close - 2 * risk, 2),
                confidence=0.65,
                context={"supertrend": st_line, "dir": int(dir_now), "atr": atr},
            )
        return None
