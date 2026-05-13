"""Classify market regime: trend / range / high_vol."""

from __future__ import annotations

from typing import Literal

import pandas as pd

from app.config import get_settings

Regime = Literal["trend_up", "trend_down", "range", "high_vol"]


def detect_regime(candles: pd.DataFrame) -> Regime:
    settings = get_settings()
    if len(candles) < 50:
        return "range"
    last = candles.iloc[-1]
    ema20 = float(last.get("ema20", float("nan")))
    ema50 = float(last.get("ema50", float("nan")))
    atr = float(last.get("atr14", float("nan")))
    close = float(last["close"])

    atr_pct = (atr / close * 100) if close else 0
    if atr_pct > settings.regime_high_vol_atr_pct_threshold:
        return "high_vol"
    if pd.isna(ema20) or pd.isna(ema50):
        return "range"
    spread_pct = abs(ema20 - ema50) / close * 100
    if spread_pct < settings.regime_range_spread_pct_threshold:
        return "range"
    return "trend_up" if ema20 > ema50 else "trend_down"
