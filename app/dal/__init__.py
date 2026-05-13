"""Data Access Layer — single entry point for every DB query in the app.

Every raw ``Session.query(...)`` should live here, not in services or routes.
DAL methods either return typed ORM rows or raise a ``DomainException`` from
``app.exceptions`` when a lookup fails — callers never see SQLAlchemy
``NoResultFound`` errors.
"""

from __future__ import annotations

from app.dal.audit_log_dal import AuditLogDAL
from app.dal.base import BaseRepository
from app.dal.position_dal import PositionDAL
from app.dal.signal_dal import SignalDAL
from app.dal.trade_dal import TradeDAL

__all__ = [
    "BaseRepository",
    "AuditLogDAL",
    "PositionDAL",
    "SignalDAL",
    "TradeDAL",
]
