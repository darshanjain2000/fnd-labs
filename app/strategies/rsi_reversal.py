from __future__ import annotations

import pandas as pd

from app.strategies.base import Signal, Strategy


class RSIReversal(Strategy):
    name = "rsi_reversal"
    preferred_regimes = ("range",)

    def __init__(self, oversold: float = 30.0, overbought: float = 70.0, atr_mult: float = 1.5) -> None:
        self.oversold = oversold
        self.overbought = overbought
        self.atr_mult = atr_mult

    def evaluate(self, symbol: str, candles: pd.DataFrame) -> Signal | None:
        if len(candles) < 20:
            return None
        last = candles.iloc[-1]
        rsi = float(last.get("rsi", float("nan")))
        atr = float(last.get("atr14", float("nan")))
        close = float(last["close"])
        if pd.isna(rsi) or pd.isna(atr):
            return None

        if rsi < self.oversold:
            return Signal(
                symbol=symbol,
                strategy=self.name,
                side="BUY",
                entry=close,
                stop_loss=round(close - self.atr_mult * atr, 2),
                target=round(close + 2 * self.atr_mult * atr, 2),
                confidence=min(1.0, (self.oversold - rsi) / self.oversold),
                context={"rsi": rsi, "atr": atr},
            )
        if rsi > self.overbought:
            return Signal(
                symbol=symbol,
                strategy=self.name,
                side="SELL",
                entry=close,
                stop_loss=round(close + self.atr_mult * atr, 2),
                target=round(close - 2 * self.atr_mult * atr, 2),
                confidence=min(1.0, (rsi - self.overbought) / (100 - self.overbought)),
                context={"rsi": rsi, "atr": atr},
            )
        return None
