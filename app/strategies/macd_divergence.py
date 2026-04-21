"""MACD zero-line crossover strategy.

Fires when the MACD line crosses above or below its signal line while still
on the opposite side of zero — a classic trend-confirmation entry.
"""
from __future__ import annotations

import pandas as pd

from app.strategies.base import Signal, Strategy


class MACDDivergence(Strategy):
    """Enter on MACD/signal crossover near the zero line.

    BUY:  MACD crosses above signal while MACD < 0 (momentum turning bullish from below zero).
    SELL: MACD crosses below signal while MACD > 0 (momentum turning bearish from above zero).

    Preferred regimes: trend_up, trend_down.
    """

    name = "macd_divergence"
    preferred_regimes = ("trend_up", "trend_down")

    def __init__(self, atr_mult: float = 1.5, reward_ratio: float = 2.0) -> None:
        """Initialise strategy parameters.

        Args:
            atr_mult: ATR multiple for stop-loss distance (default 1.5).
            reward_ratio: Risk-reward ratio for target (default 2.0).
        """
        self.atr_mult = atr_mult
        self.reward_ratio = reward_ratio

    def evaluate(self, symbol: str, candles: pd.DataFrame) -> Signal | None:
        """Fire on MACD/signal crossover near zero.

        Args:
            symbol: NSE trading symbol.
            candles: OHLCV DataFrame with macd, macd_signal, atr14 columns.

        Returns:
            Signal on crossover; None otherwise.
        """
        if len(candles) < 35:
            return None
        last = candles.iloc[-1]
        prev = candles.iloc[-2]

        macd = float(last.get("macd", float("nan")))
        macd_prev = float(prev.get("macd", float("nan")))
        sig_line = float(last.get("macd_signal", float("nan")))
        sig_prev = float(prev.get("macd_signal", float("nan")))
        atr = float(last.get("atr14", float("nan")))
        close = float(last["close"])

        if any(pd.isna(v) for v in (macd, macd_prev, sig_line, sig_prev, atr)):
            return None

        stop_dist = self.atr_mult * atr
        target_dist = self.reward_ratio * stop_dist

        # Bullish crossover: MACD crosses above signal below zero
        if macd_prev < sig_prev and macd > sig_line and macd < 0:
            return Signal(
                symbol=symbol,
                strategy=self.name,
                side="BUY",
                entry=close,
                stop_loss=round(close - stop_dist, 2),
                target=round(close + target_dist, 2),
                confidence=0.60,
                context={"macd": macd, "macd_signal": sig_line, "hist": macd - sig_line},
            )
        # Bearish crossover: MACD crosses below signal above zero
        if macd_prev > sig_prev and macd < sig_line and macd > 0:
            return Signal(
                symbol=symbol,
                strategy=self.name,
                side="SELL",
                entry=close,
                stop_loss=round(close + stop_dist, 2),
                target=round(close - target_dist, 2),
                confidence=0.60,
                context={"macd": macd, "macd_signal": sig_line, "hist": macd - sig_line},
            )
        return None
