"""SQL-backed alternative to RAG.

Feeds the LLM validator with structured facts from past trades:
- The last k closed trades matching symbol + strategy + side.
- Aggregate stats: wins / losses / win-rate / avg PnL.

For structured intraday data with a modest trade count, this is cheaper,
deterministic, and more informative than embedding-based retrieval.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models.trade import Trade


@dataclass
class TradeStats:
    total: int
    wins: int
    losses: int
    win_rate: float
    avg_pnl: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "wins": self.wins,
            "losses": self.losses,
            "win_rate": round(self.win_rate, 3),
            "avg_pnl": round(self.avg_pnl, 2),
        }


class TradeMemory:
    def __init__(self, session_factory: Callable[[], Session] = SessionLocal) -> None:
        self._session_factory = session_factory

    # ---- raw fetches ------------------------------------------------------
    def recent_similar(
        self,
        symbol: str,
        strategy: str | None,
        side: str | None,
        k: int = 5,
    ) -> list[dict[str, Any]]:
        """Last k CLOSED trades matching the filters. Most recent first."""
        with self._session_factory() as session:
            q = session.query(Trade).filter(Trade.status == "CLOSED", Trade.symbol == symbol)
            if strategy:
                q = q.filter(Trade.strategy == strategy)
            if side:
                q = q.filter(Trade.side == side)
            rows = q.order_by(Trade.closed_at.desc().nullslast()).limit(k).all()
            return [self._row_to_dict(r) for r in rows]

    def stats(self, symbol: str, strategy: str | None, side: str | None) -> TradeStats:
        with self._session_factory() as session:
            q = session.query(
                func.count(Trade.id),
                func.sum(Trade.pnl),
                func.sum(case((Trade.pnl > 0, 1), else_=0)),
            ).filter(Trade.status == "CLOSED", Trade.symbol == symbol)
            if strategy:
                q = q.filter(Trade.strategy == strategy)
            if side:
                q = q.filter(Trade.side == side)
            total, total_pnl, wins = q.one()
        total = int(total or 0)
        wins = int(wins or 0)
        losses = total - wins
        win_rate = (wins / total) if total else 0.0
        avg_pnl = (float(total_pnl) / total) if total else 0.0
        return TradeStats(total=total, wins=wins, losses=losses, win_rate=win_rate, avg_pnl=avg_pnl)

    # ---- LLM-facing format ------------------------------------------------
    def format_context(
        self,
        symbol: str,
        strategy: str | None,
        side: str | None,
        k: int = 5,
    ) -> list[str]:
        """Return a list of short strings, same shape as RAGStore.query_similar."""
        recent = self.recent_similar(symbol, strategy, side, k=k)
        stats = self.stats(symbol, strategy, side)

        lines: list[str] = []
        if stats.total:
            lines.append(
                f"History[{symbol} {strategy or 'any'} {side or 'any'}]: "
                f"{stats.total} trades, {stats.wins}W/{stats.losses}L, "
                f"win_rate={stats.win_rate:.0%}, avg_pnl=₹{stats.avg_pnl:.0f}"
            )
        for r in recent:
            lines.append(
                f"Past: {r['side']} {r['symbol']} @ {r['entry_price']} -> "
                f"{r['exit_price']} pnl=₹{r['pnl']:.0f} "
                f"({r['strategy'] or '?'})"
            )
        return lines

    # ---- helpers ----------------------------------------------------------
    @staticmethod
    def _row_to_dict(t: Trade) -> dict[str, Any]:
        return {
            "id": t.id,
            "symbol": t.symbol,
            "strategy": t.strategy,
            "side": t.side,
            "qty": t.qty,
            "entry_price": t.entry_price,
            "exit_price": t.exit_price,
            "pnl": t.pnl,
            "opened_at": t.opened_at.isoformat() if t.opened_at else None,
            "closed_at": t.closed_at.isoformat() if t.closed_at else None,
        }
