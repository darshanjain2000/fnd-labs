"""Signal repository — all DB access for the ``signals`` table."""
from __future__ import annotations

from sqlalchemy import desc

from app.dal.base import BaseRepository
from app.exceptions.domain import SignalNotFoundException
from app.models.trade import Signal


class SignalDAL(BaseRepository):
    """CRUD + queries for the ``Signal`` ORM model."""

    def get_by_id(self, signal_id: int) -> Signal:
        """Fetch a signal by primary key or raise ``SignalNotFoundException``."""
        with self._session() as session:
            s = session.get(Signal, signal_id)
            if s is None:
                raise SignalNotFoundException(f"signal {signal_id} not found")
            session.expunge(s)
            return s

    def list_recent(self, limit: int = 50) -> list[Signal]:
        """Return the most recent signals, newest first."""
        with self._session() as session:
            rows = session.query(Signal).order_by(desc(Signal.created_at)).limit(limit).all()
            for r in rows:
                session.expunge(r)
            return rows
