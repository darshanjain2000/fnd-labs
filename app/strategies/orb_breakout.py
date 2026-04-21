"""Opening Range Breakout (ORB) strategy.

The ORB strategy defines the high and low of the first ``orb_minutes`` of
trading (09:15–09:45 IST by default) as the "opening range". A breakout
above the range high or below the range low signals a directional trade.

Requires a ``pd.DatetimeIndex`` on the candles DataFrame (timezone-aware or
naive IST). If the index is not a DatetimeIndex, the strategy returns None.
"""
from __future__ import annotations

import pandas as pd

from app.strategies.base import Signal, Strategy


class ORBBreakout(Strategy):
    """Opening Range Breakout — trade the first directional push of the day.

    Setup:
    - Opening range = high/low of the first ``orb_minutes`` of the session.
    - Signal fires when the *previous* close was inside the range and the
      *current* close breaks out.
    - Target = entry ± OR width (1:1 extension of the opening range).
    - Stop-loss = opposite end of the opening range.

    Preferred regimes: trend_up, trend_down, high_vol.
    """

    name = "orb_breakout"
    preferred_regimes = ("trend_up", "trend_down", "high_vol")

    def __init__(self, orb_minutes: int = 30, atr_mult: float = 1.5) -> None:
        """Initialise strategy parameters.

        Args:
            orb_minutes: Length of the opening range in minutes (default 30).
            atr_mult: ATR multiple used as a fallback stop if OR width is
                suspiciously narrow (default 1.5).
        """
        self.orb_minutes = orb_minutes
        self.atr_mult = atr_mult

    def evaluate(self, symbol: str, candles: pd.DataFrame) -> Signal | None:
        """Fire on a breakout above/below the session opening range.

        Args:
            symbol: NSE trading symbol.
            candles: OHLCV DataFrame with a DatetimeIndex (IST). Requires atr14.

        Returns:
            Signal on breakout; None if ORB has not formed or no breakout.
        """
        if len(candles) < 5:
            return None
        if not isinstance(candles.index, pd.DatetimeIndex):
            return None

        last = candles.iloc[-1]
        prev = candles.iloc[-2]
        close = float(last["close"])
        prev_close = float(prev["close"])
        atr = float(last.get("atr14", float("nan")))
        if pd.isna(atr):
            return None

        # Build the opening range from today's candles only
        today = candles.index[-1].date()
        today_candles = candles[candles.index.date == today]
        if today_candles.empty:
            return None

        orb_end = today_candles.index[0] + pd.Timedelta(minutes=self.orb_minutes)
        orb_candles = today_candles[today_candles.index <= orb_end]

        # Need at least 2 ORB candles and must now be past the ORB window
        if len(orb_candles) < 2 or candles.index[-1] <= orb_end:
            return None

        orb_high = float(orb_candles["high"].max())
        orb_low = float(orb_candles["low"].min())
        or_width = orb_high - orb_low
        if or_width <= 0:
            return None

        # Upside breakout
        if prev_close <= orb_high and close > orb_high:
            return Signal(
                symbol=symbol,
                strategy=self.name,
                side="BUY",
                entry=close,
                stop_loss=round(orb_low, 2),
                target=round(close + or_width, 2),
                confidence=0.65,
                context={"orb_high": orb_high, "orb_low": orb_low, "or_width": or_width},
            )
        # Downside breakdown
        if prev_close >= orb_low and close < orb_low:
            return Signal(
                symbol=symbol,
                strategy=self.name,
                side="SELL",
                entry=close,
                stop_loss=round(orb_high, 2),
                target=round(close - or_width, 2),
                confidence=0.65,
                context={"orb_high": orb_high, "orb_low": orb_low, "or_width": or_width},
            )
        return None
