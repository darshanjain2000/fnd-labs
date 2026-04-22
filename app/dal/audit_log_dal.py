"""Audit-log repository — all DB access for the ``audit_log`` table."""
from __future__ import annotations

from sqlalchemy import desc

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
            rows = session.query(AuditLog).order_by(desc(AuditLog.at)).limit(limit).all()
            for r in rows:
                session.expunge(r)
            return rows
