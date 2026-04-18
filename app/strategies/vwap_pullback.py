from __future__ import annotations

import pandas as pd

from strategies.base import Signal, Strategy


class VWAPPullback(Strategy):
    name = "vwap_pullback"

    def __init__(self, tolerance_pct: float = 0.2, atr_mult: float = 1.2) -> None:
        self.tolerance_pct = tolerance_pct
        self.atr_mult = atr_mult

    def evaluate(self, symbol: str, candles: pd.DataFrame) -> Signal | None:
        if len(candles) < 30:
            return None
        last = candles.iloc[-1]
        close = float(last["close"])
        vwap = float(last.get("vwap", float("nan")))
        ema20 = float(last.get("ema20", float("nan")))
        atr = float(last.get("atr14", float("nan")))
        if any(pd.isna(v) for v in (vwap, ema20, atr)):
            return None

        near_vwap = abs(close - vwap) / vwap * 100 <= self.tolerance_pct
        if not near_vwap:
            return None

        if close > ema20:  # uptrend pullback
            return Signal(
                symbol=symbol, strategy=self.name, side="BUY", entry=close,
                stop_loss=round(close - self.atr_mult * atr, 2),
                target=round(close + 2 * self.atr_mult * atr, 2),
                confidence=0.55,
                context={"vwap": vwap, "ema20": ema20},
            )
        if close < ema20:
            return Signal(
                symbol=symbol, strategy=self.name, side="SELL", entry=close,
                stop_loss=round(close + self.atr_mult * atr, 2),
                target=round(close - 2 * self.atr_mult * atr, 2),
                confidence=0.55,
                context={"vwap": vwap, "ema20": ema20},
            )
        return None
