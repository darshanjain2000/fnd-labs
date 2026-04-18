from __future__ import annotations

import pandas as pd

from strategies.base import Signal, Strategy


class EMABreakout(Strategy):
    name = "ema_breakout"

    def __init__(self, atr_mult: float = 1.5) -> None:
        self.atr_mult = atr_mult

    def evaluate(self, symbol: str, candles: pd.DataFrame) -> Signal | None:
        if len(candles) < 52:
            return None
        last = candles.iloc[-1]
        prev = candles.iloc[-2]
        ema20, ema50 = float(last.get("ema20", float("nan"))), float(last.get("ema50", float("nan")))
        p_ema20, p_ema50 = float(prev.get("ema20", float("nan"))), float(prev.get("ema50", float("nan")))
        atr = float(last.get("atr14", float("nan")))
        close = float(last["close"])
        if any(pd.isna(v) for v in (ema20, ema50, p_ema20, p_ema50, atr)):
            return None

        if p_ema20 <= p_ema50 and ema20 > ema50:
            return Signal(
                symbol=symbol, strategy=self.name, side="BUY", entry=close,
                stop_loss=round(close - self.atr_mult * atr, 2),
                target=round(close + 2 * self.atr_mult * atr, 2),
                confidence=0.6,
                context={"ema20": ema20, "ema50": ema50},
            )
        if p_ema20 >= p_ema50 and ema20 < ema50:
            return Signal(
                symbol=symbol, strategy=self.name, side="SELL", entry=close,
                stop_loss=round(close + self.atr_mult * atr, 2),
                target=round(close - 2 * self.atr_mult * atr, 2),
                confidence=0.6,
                context={"ema20": ema20, "ema50": ema50},
            )
        return None
