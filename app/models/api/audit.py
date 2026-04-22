"""Pydantic DTOs for the ``/logs`` router."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel

from app.models.trade import AuditLog


class AuditLogOut(BaseModel):
    """Serialisable view of an ``AuditLog`` row."""

    id: int | None
    at: datetime | None
    event: str
    payload: dict[str, Any]

    @classmethod
    def from_row(cls, r: AuditLog) -> AuditLogOut:
        """Build a DTO from a detached ``AuditLog`` ORM row."""
        return cls(id=r.id, at=r.at, event=r.event, payload=r.payload or {})


class AuditLogListOut(BaseModel):
    """List envelope: count + logs."""

    count: int
    logs: list[AuditLogOut]
