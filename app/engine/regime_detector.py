"""Classify market regime: trend / range / high_vol."""
from __future__ import annotations

from typing import Literal

import pandas as pd

Regime = Literal["trend_up", "trend_down", "range", "high_vol"]


def detect_regime(candles: pd.DataFrame) -> Regime:
    if len(candles) < 50:
        return "range"
    last = candles.iloc[-1]
    ema20 = float(last.get("ema20", float("nan")))
    ema50 = float(last.get("ema50", float("nan")))
    atr = float(last.get("atr14", float("nan")))
    close = float(last["close"])

    atr_pct = (atr / close * 100) if close else 0
    if atr_pct > 2.0:
        return "high_vol"
    if pd.isna(ema20) or pd.isna(ema50):
        return "range"
    spread_pct = abs(ema20 - ema50) / close * 100
    if spread_pct < 0.2:
        return "range"
    return "trend_up" if ema20 > ema50 else "trend_down"
