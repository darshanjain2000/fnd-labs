"""Pydantic DTOs for the ``/admin`` router."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class PositionsOut(BaseModel):
    """Live risk engine position snapshot."""

    open_positions: int
    trades_today: int
    realized_pnl_today: float
    last_reset: str


class KillSwitchOut(BaseModel):
    """Response envelope for ``POST /admin/killswitch/{state}``."""

    kill_switch: bool


class BrokerStatusOut(BaseModel):
    """Response envelope for ``GET /admin/broker/status``."""

    configured_broker: str
    paper_trade_flag: bool
    active_mode: str
    active_class: str
    probe: dict[str, Any]


class AngelTotpOut(BaseModel):
    """Response envelope for ``GET /admin/angel/totp`` (diagnostic)."""

    ok: bool
    error: str | None = None
    current_code: str | None = None
    previous_code: str | None = None
    next_code: str | None = None
    seconds_remaining: int | None = None
    client_code: str | None = None
    secret_length: int | None = None
    note: str | None = None
