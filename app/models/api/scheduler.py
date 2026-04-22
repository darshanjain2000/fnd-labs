"""Pydantic DTOs for the ``/runner`` router."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class RunnerStartOut(BaseModel):
    """Response envelope for ``POST /runner/start``."""

    started: bool
    already_running: bool


class RunnerStatusOut(BaseModel):
    """Live scheduler snapshot."""

    running: bool
    started_at: datetime | None
    last_tick_at: datetime | None
    ticks: int
    signals_seen: int
    trades_opened: int
    trades_auto_closed: int
    last_error: str | None
    watchlist: list[str]


class RunnerStopOut(BaseModel):
    """Response envelope for ``POST /runner/stop``."""

    stopped: bool
    status: RunnerStatusOut
