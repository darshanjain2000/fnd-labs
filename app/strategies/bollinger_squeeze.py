"""Bollinger Band squeeze breakout strategy.

A squeeze occurs when the band width narrows below a threshold, indicating
low volatility. When price breaks out of the band after a squeeze, momentum
tends to be strong and directional.
"""

from __future__ import annotations

import pandas as pd

from app.strategies.base import Signal, Strategy


class BollingerSqueeze(Strategy):
    """Break out of Bollinger Bands after a low-volatility squeeze.

    Conditions:
    - Current BB width (as % of mid) is below ``squeeze_pct``.
    - Previous candle close was inside the band; current close breaks out.

    Stop-loss is placed at the Bollinger mid (20-period SMA).
    Preferred regimes: range only - squeeze setups are a ranging-market pattern.
    """

    name = "bollinger_squeeze"
    preferred_regimes = ("range",)

    def __init__(self, squeeze_pct: float = 2.0, atr_mult: float = 1.5) -> None:
        """Initialise strategy parameters.

        Args:
            squeeze_pct: Maximum BB width (%) to qualify as a squeeze (default 2.0).
            atr_mult: ATR multiple for target extension beyond breakout (default 1.5).
        """
        self.squeeze_pct = squeeze_pct
        self.atr_mult = atr_mult

    def evaluate(self, symbol: str, candles: pd.DataFrame) -> Signal | None:
        """Fire on a post-squeeze breakout above/below the Bollinger Bands.

        Args:
            symbol: NSE trading symbol.
            candles: OHLCV DataFrame with bb_upper/bb_mid/bb_lower/bb_width, atr14.

        Returns:
            Signal on breakout; None otherwise.
        """
        if len(candles) < 30:
            return None
        last = candles.iloc[-1]
        prev = candles.iloc[-2]

        bb_upper = float(last.get("bb_upper", float("nan")))
        bb_lower = float(last.get("bb_lower", float("nan")))
        bb_mid = float(last.get("bb_mid", float("nan")))
        bb_width = float(last.get("bb_width", float("nan")))
        atr = float(last.get("atr14", float("nan")))
        close = float(last["close"])

        prev_bb_upper = float(prev.get("bb_upper", float("nan")))
        prev_bb_lower = float(prev.get("bb_lower", float("nan")))
        prev_close = float(prev["close"])

        if any(
            pd.isna(v)
            for v in (
                bb_upper,
                bb_lower,
                bb_mid,
                bb_width,
                atr,
                prev_bb_upper,
                prev_bb_lower,
            )
        ):
            return None

        # Must be in a squeeze (band width as ratio, convert to %)
        if bb_width * 100 > self.squeeze_pct:
            return None

        # Upside breakout
        if prev_close <= prev_bb_upper and close > bb_upper:
            return Signal(
                symbol=symbol,
                strategy=self.name,
                side="BUY",
                entry=close,
                stop_loss=round(bb_mid, 2),
                target=round(close + self.atr_mult * atr, 2),
                confidence=0.62,
                context={
                    "bb_width_pct": round(bb_width * 100, 3),
                    "bb_upper": bb_upper,
                },
            )
        # Downside breakdown
        if prev_close >= prev_bb_lower and close < bb_lower:
            return Signal(
                symbol=symbol,
                strategy=self.name,
                side="SELL",
                entry=close,
                stop_loss=round(bb_mid, 2),
                target=round(close - self.atr_mult * atr, 2),
                confidence=0.62,
                context={
                    "bb_width_pct": round(bb_width * 100, 3),
                    "bb_lower": bb_lower,
                },
            )
        return None
