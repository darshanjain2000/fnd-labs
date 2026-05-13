"""Position repository — all DB access for the ``positions`` table."""

from __future__ import annotations

from app.dal.base import BaseRepository
from app.models.trade import Position


class PositionDAL(BaseRepository):
    """CRUD + queries for the ``Position`` ORM model."""

    def get_by_symbol(self, symbol: str) -> Position | None:
        """Return the position row for ``symbol`` or ``None``."""
        with self._session() as session:
            row = (
                session.query(Position).filter(Position.symbol == symbol).one_or_none()
            )
            if row is None:
                return None
            session.expunge(row)
            return row

    def get_net_position(self, symbol: str) -> int:
        """Return the signed net quantity for ``symbol`` (0 if no row)."""
        pos = self.get_by_symbol(symbol)
        return int(pos.qty) if pos else 0
