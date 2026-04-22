"""Trade repository — all DB access for the ``trades`` table."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import desc

from app.dal.base import BaseRepository
from app.exceptions.domain import TradeNotFoundException
from app.models.trade import AuditLog, Trade


class TradeDAL(BaseRepository):
    """CRUD + queries for the ``Trade`` ORM model.

    Every read path either returns a detached/expunged ``Trade`` (safe to
    access attributes outside the session) or raises a domain exception.
    Write paths accept an open ``Trade`` instance and commit it for you.
    """

    # ---- reads ---------------------------------------------------------

    def list_recent(self, limit: int = 50) -> list[Trade]:
        """Return the most recent trades, newest first."""
        with self._session() as session:
            rows = session.query(Trade).order_by(desc(Trade.opened_at)).limit(limit).all()
            for r in rows:
                session.expunge(r)
            return rows

    def get_by_id(self, trade_id: int) -> Trade:
        """Fetch a trade by primary key or raise ``TradeNotFoundException``."""
        with self._session() as session:
            t = session.get(Trade, trade_id)
            if t is None:
                raise TradeNotFoundException(f"trade {trade_id} not found")
            session.expunge(t)
            return t

    def find_by_id(self, trade_id: int) -> Trade | None:
        """Fetch a trade by primary key or return ``None`` (no exception)."""
        with self._session() as session:
            t = session.get(Trade, trade_id)
            if t is None:
                return None
            session.expunge(t)
            return t

    def find_open(self) -> list[Trade]:
        """Return every ``Trade`` with status ``OPEN``."""
        with self._session() as session:
            rows = session.query(Trade).filter(Trade.status == "OPEN").all()
            for r in rows:
                session.expunge(r)
            return rows

    def list_open_symbols(self) -> list[str]:
        """Return the set of symbols with open trades."""
        with self._session() as session:
            rows = (
                session.query(Trade.symbol)
                .filter(Trade.status == "OPEN")
                .distinct()
                .all()
            )
            return [r[0] for r in rows]

    def find_by_broker_order_id(self, broker_order_id: str) -> int | None:
        """Return the PK of the trade with the given broker order id, or ``None``."""
        with self._session() as session:
            return (
                session.query(Trade.id)
                .filter(Trade.broker_order_id == broker_order_id)
                .scalar()
            )

    def find_closed_by_symbol(
        self,
        symbol: str,
        *,
        strategy: str | None = None,
        side: str | None = None,
        limit: int = 5,
    ) -> list[Trade]:
        """Return the last ``limit`` CLOSED trades for ``symbol`` (most recent first)."""
        with self._session() as session:
            q = session.query(Trade).filter(Trade.status == "CLOSED", Trade.symbol == symbol)
            if strategy:
                q = q.filter(Trade.strategy == strategy)
            if side:
                q = q.filter(Trade.side == side)
            rows = q.order_by(Trade.closed_at.desc().nullslast()).limit(limit).all()
            for r in rows:
                session.expunge(r)
            return rows

    # ---- writes --------------------------------------------------------

    def open_with_audit(
        self,
        trade_kwargs: dict[str, Any],
        audit_payload: dict[str, Any],
        *,
        audit_event: str = "trade_opened",
    ) -> Trade:
        """Insert a new ``OPEN`` trade and an accompanying audit log in one txn.

        Args:
            trade_kwargs: Keyword args for the ``Trade`` constructor.
            audit_payload: JSON-safe payload for the ``AuditLog`` row.
            audit_event: Event name on the audit row (default ``trade_opened``).

        Returns:
            The inserted ``Trade`` row with its new primary key, detached from
            the internal session so callers may read attributes freely.
        """
        with self._session() as session:
            trade = Trade(**trade_kwargs)
            session.add(trade)
            session.add(AuditLog(event=audit_event, payload=audit_payload))
            session.commit()
            session.refresh(trade)
            session.expunge(trade)
            return trade

    def close_with_audit(
        self,
        trade_id: int,
        *,
        exit_price: float,
        pnl: float,
        closed_at: datetime,
        status: str = "CLOSED",
        audit_event: str,
        audit_payload: dict[str, Any],
    ) -> Trade | None:
        """Close a trade and write an audit log in a single transaction.

        Args:
            trade_id: Primary key of the trade to close.
            exit_price: Fill price for the closing leg.
            pnl: Realised profit/loss on the position.
            closed_at: Close timestamp (UTC).
            status: New status to set on the trade (defaults to ``CLOSED``).
            audit_event: Event name on the audit row.
            audit_payload: JSON-safe payload for the audit row.

        Returns:
            The refreshed detached ``Trade`` row on success, ``None`` if the
            trade does not exist or is not in ``OPEN`` status.
        """
        with self._session() as session:
            trade = session.get(Trade, trade_id)
            if trade is None or trade.status != "OPEN":
                if trade is not None:
                    session.expunge(trade)
                return trade
            trade.exit_price = exit_price
            trade.pnl = pnl
            trade.status = status
            trade.closed_at = closed_at
            session.add(AuditLog(event=audit_event, payload=audit_payload))
            session.commit()
            session.refresh(trade)
            session.expunge(trade)
            return trade
