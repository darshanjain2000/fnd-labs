"""Pydantic DTOs for the ``/analyze`` router."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class Candle(BaseModel):
    """Single OHLCV bar."""

    open: float
    high: float
    low: float
    close: float
    volume: float


class AnalyzeRequest(BaseModel):
    """Request body for ``POST /analyze``."""

    symbol: str = Field(..., examples=["NIFTY24APR22500CE"])
    candles: list[Candle] = Field(..., min_length=20)
    is_expiry_day: bool = False
    mock_quote: float | None = None


class LiveAnalyzeRequest(BaseModel):
    """Request body for ``POST /analyze/live``."""

    symbol: str = Field(..., examples=["NIFTY25APR22500CE"])
    exchange: str = Field("NFO", examples=["NFO", "NSE", "BSE"])
    interval: str = Field("5m", examples=["1m", "3m", "5m", "15m", "30m", "1h"])
    from_dt: datetime | None = Field(None, description="Start datetime (default: 80 bars back)")
    to_dt: datetime | None = Field(None, description="End datetime (default: now)")
    is_expiry_day: bool = False


class AnalyzeOut(BaseModel):
    """Response envelope for ``POST /analyze``."""

    symbol: str
    outcomes: list[dict[str, Any]]


class LiveAnalyzeOut(BaseModel):
    """Response envelope for ``POST /analyze/live``."""

    symbol: str
    exchange: str
    interval: str
    candles_used: int
    last_close: float
    outcomes: list[dict[str, Any]]
