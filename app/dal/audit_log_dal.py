"""Audit-log repository — all DB access for the ``audit_log`` table."""

from __future__ import annotations

from sqlalchemy import desc, func

from app.dal.base import BaseRepository
from app.models.trade import AuditLog


class AuditLogDAL(BaseRepository):
    """Read-only queries for the ``AuditLog`` ORM model.

    Audit-log rows are written inline inside execution/close workflows
    (same session/transaction as the Trade write), so there's no ``save``
    method here — only reads for the admin UI.
    """

    def list_recent(self, limit: int = 50) -> list[AuditLog]:
        """Return the most recent audit-log events, newest first."""
        with self._session() as session:
            rows = (
                session.query(AuditLog).order_by(desc(AuditLog.at)).limit(limit).all()
            )
            for r in rows:
                session.expunge(r)
            return rows

    def list_by_trade_id(self, trade_id: int) -> list[AuditLog]:
        """Return all audit events whose payload contains ``trade_id``, oldest first."""
        with self._session() as session:
            rows = (
                session.query(AuditLog)
                .filter(func.json_extract(AuditLog.payload, "$.trade_id") == trade_id)
                .order_by(AuditLog.at)
                .all()
            )
            for r in rows:
                session.expunge(r)
            return rows
