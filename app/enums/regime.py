"""Market-regime enum used by ``regime_detector`` and strategy preferences.

A ``StrEnum`` keeps wire-format (``"range"``, ``"trend_up"``, ...) identical
to the legacy ``Literal`` alias in ``app.strategies.base`` and
``app.engine.regime_detector``, so existing call sites that compare to
raw strings continue to work without change.
"""
from __future__ import annotations

from enum import StrEnum


class Regime(StrEnum):
    """Classification of current market behaviour."""

    TREND_UP = "trend_up"
    TREND_DOWN = "trend_down"
    RANGE = "range"
    HIGH_VOL = "high_vol"
