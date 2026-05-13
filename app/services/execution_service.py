"""Broker-facing execution service.

Places entry + SL orders, persists Trade + AuditLog through ``TradeDAL``
atomic methods, and owns mark-to-market and end-of-day square-off logic
for open positions.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.dal.trade_dal import TradeDAL
from app.db import SessionLocal
from app.models.trade import Trade
from app.services.broker.base import Broker, OrderRequest, OrderResult
from app.strategies.base import Signal

log = get_logger(__name__)


def _compute_pnl(side: str, entry_price: float, exit_price: float, qty: int) -> float:
    """Return realised PnL for a closed position.

    Args:
        side: ``"BUY"`` for long, anything else treated as short.
        entry_price: Fill price at entry.
        exit_price: Fill price at exit.
        qty: Position size.

    Returns:
        PnL rounded to 2 decimals.
    """
    sign = 1 if side == "BUY" else -1
    return round(sign * (exit_price - entry_price) * qty, 2)


class ExecutionService:
    """Places orders and persists their lifecycle via DAL-backed atomic writes."""

    def __init__(
        self,
        broker: Broker,
        *,
        trade_dal: TradeDAL | None = None,
        session_factory: Callable[[], Session] = SessionLocal,
    ) -> None:
        """Initialise the service.

        Args:
            broker: ``Broker`` Protocol implementation (paper / kite / angel).
            trade_dal: Injected DAL. Defaults to a new ``TradeDAL`` bound to
                ``session_factory``.
            session_factory: SQLAlchemy session factory (kept for DAL wiring
                and tests that need a shared factory).
        """
        self.broker = broker
        self._trade_dal = trade_dal or TradeDAL(session_factory=session_factory)

    def execute(
        self,
        signal: Signal,
        qty: int,
        signal_row_id: int | None = None,
    ) -> OrderResult:
        """Place entry + stop-loss orders and persist the resulting Trade.

        Args:
            signal: Validated signal to execute.
            qty: Position size (already risk-adjusted by the caller).
            signal_row_id: Optional ``signals.id`` to link on the Trade row.

        Returns:
            The broker's ``OrderResult`` for the entry leg.
        """
        entry_req = OrderRequest(
            symbol=signal.symbol,
            side=signal.side,
            qty=qty,
            order_type="MARKET",
            product="MIS",
            tag=signal.strategy[:20],
        )
        entry = self.broker.place_order(entry_req)

        sl_side = "SELL" if signal.side == "BUY" else "BUY"
        sl_req = OrderRequest(
            symbol=signal.symbol,
            side=sl_side,  # type: ignore[arg-type]
            qty=qty,
            order_type="SL-M",
            trigger_price=signal.stop_loss,
            tag=f"{signal.strategy[:16]}-SL",
        )
        sl = self.broker.place_order(sl_req)

        trade = self._trade_dal.open_with_audit(
            trade_kwargs={
                "signal_id": signal_row_id,
                "opened_at": datetime.utcnow(),
                "symbol": signal.symbol,
                "strategy": signal.strategy,
                "side": signal.side,
                "qty": qty,
                "entry_price": entry.avg_price or signal.entry,
                "stop_loss": signal.stop_loss,
                "target": signal.target,
                "mode": self.broker.mode,
                "status": "OPEN",
                "broker_order_id": entry.order_id,
                "entry_context": signal.context or {},
            },
            audit_payload={
                "entry": entry.__dict__,
                "sl": sl.__dict__,
                "qty": qty,
                "signal": {
                    "symbol": signal.symbol,
                    "strategy": signal.strategy,
                    "side": signal.side,
                    "entry": signal.entry,
                    "stop_loss": signal.stop_loss,
                    "target": signal.target,
                },
            },
        )
        log.info(
            "execution_done",
            trade_id=trade.id,
            symbol=signal.symbol,
            side=signal.side,
            qty=qty,
            fill=entry.avg_price,
            order_id=entry.order_id,
        )
        return entry

    def close_trade(self, trade_id: int, exit_price: float) -> Trade | None:
        """Close an ``OPEN`` trade at the given exit price and log the event.

        Args:
            trade_id: Primary key of the Trade to close.
            exit_price: Fill price for the closing leg.

        Returns:
            The refreshed detached ``Trade`` row, or ``None`` if the trade
            does not exist or is not in ``OPEN`` status.
        """
        probe = self._trade_dal.find_by_id(trade_id)
        if probe is None or probe.status != "OPEN":
            return probe
        pnl = _compute_pnl(probe.side, probe.entry_price, exit_price, probe.qty)
        trade = self._trade_dal.close_with_audit(
            trade_id,
            exit_price=exit_price,
            pnl=pnl,
            closed_at=datetime.utcnow(),
            audit_event="trade_closed",
            audit_payload={"trade_id": trade_id, "exit_price": exit_price, "pnl": pnl},
        )
        if trade is not None:
            log.info("trade_closed", trade_id=trade_id, pnl=trade.pnl)
        return trade

    def mark_to_market(
        self,
        latest_prices: dict[str, float],
        reason_tag: str = "mtm",
    ) -> list[Trade]:
        """Auto-close every open trade whose SL or target has been breached.

        Args:
            latest_prices: Map of symbol to last-close price.
            reason_tag: Tag stored on the audit log payload for traceability.

        Returns:
            List of trades that were just closed (may be empty).
        """
        closed: list[Trade] = []
        for t in self._trade_dal.find_open():
            last = latest_prices.get(t.symbol)
            if last is None:
                continue
            reason = self._breach_reason(t.side, last, t.stop_loss, t.target)
            if reason is None:
                continue
            pnl = _compute_pnl(t.side, t.entry_price, last, t.qty)
            updated = self._trade_dal.close_with_audit(
                t.id,
                exit_price=last,
                pnl=pnl,
                closed_at=datetime.utcnow(),
                audit_event="trade_auto_closed",
                audit_payload={
                    "trade_id": t.id,
                    "symbol": t.symbol,
                    "side": t.side,
                    "exit_price": last,
                    "pnl": pnl,
                    "reason": reason,
                    "tag": reason_tag,
                },
            )
            if updated is None:
                continue
            # Cancel SL leg on broker (best-effort; ignore any failure).
            # Broker APIs can raise network/auth errors or reject on already-
            # cancelled orders — none of which should block the MTM sweep.
            try:
                if updated.broker_order_id:
                    self.broker.cancel_order(updated.broker_order_id + "-SL")
            except Exception:  # pragma: no cover
                pass
            closed.append(updated)
            log.info(
                "trade_auto_closed",
                trade_id=updated.id,
                symbol=updated.symbol,
                side=updated.side,
                exit_price=last,
                pnl=updated.pnl,
                reason=reason,
            )
        return closed

    def force_close_all(
        self,
        latest_prices: dict[str, float],
        reason: str = "square_off",
    ) -> list[Trade]:
        """Close every open trade at the provided last price (EOD square-off).

        Args:
            latest_prices: Map of symbol to last price. Missing symbols fall
                back to the trade's entry price (zero PnL).
            reason: Tag stored on the audit payload (``"square_off"`` at EOD).

        Returns:
            List of trades that were just closed (may be empty).
        """
        closed: list[Trade] = []
        for t in self._trade_dal.find_open():
            last = latest_prices.get(t.symbol, t.entry_price)
            pnl = _compute_pnl(t.side, t.entry_price, last, t.qty)
            updated = self._trade_dal.close_with_audit(
                t.id,
                exit_price=last,
                pnl=pnl,
                closed_at=datetime.utcnow(),
                audit_event="trade_force_closed",
                audit_payload={
                    "trade_id": t.id,
                    "exit_price": last,
                    "pnl": pnl,
                    "reason": reason,
                },
            )
            if updated is None:
                continue
            closed.append(updated)
            log.info(
                "trade_force_closed",
                trade_id=updated.id,
                pnl=updated.pnl,
                reason=reason,
            )
        return closed

    @staticmethod
    def _breach_reason(
        side: str,
        last: float,
        stop_loss: float,
        target: float | None,
    ) -> str | None:
        """Return ``"stop_loss_hit"``, ``"target_hit"`` or ``None``.

        Args:
            side: ``"BUY"`` or ``"SELL"``.
            last: Most recent close price for the symbol.
            stop_loss: Stop-loss price on the trade.
            target: Target price on the trade (optional).
        """
        if side == "BUY":
            if last <= stop_loss:
                return "stop_loss_hit"
            if target and last >= target:
                return "target_hit"
        else:  # SELL
            if last >= stop_loss:
                return "stop_loss_hit"
            if target and last <= target:
                return "target_hit"
        return None
