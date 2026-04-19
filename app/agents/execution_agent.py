"""Execution Agent: places orders via broker AND persists Trade + AuditLog rows."""
from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.db import SessionLocal
from app.models.trade import AuditLog, Trade
from app.services.broker.base import Broker, OrderRequest, OrderResult
from app.strategies.base import Signal

log = get_logger(__name__)


class ExecutionAgent:
    def __init__(
        self,
        broker: Broker,
        session_factory: Callable[[], Session] = SessionLocal,
    ) -> None:
        self.broker = broker
        self._session_factory = session_factory

    def execute(self, signal: Signal, qty: int, signal_row_id: int | None = None) -> OrderResult:
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

        with self._session_factory() as session:
            trade = Trade(
                signal_id=signal_row_id,
                opened_at=datetime.utcnow(),
                symbol=signal.symbol,
                strategy=signal.strategy,
                side=signal.side,
                qty=qty,
                entry_price=entry.avg_price or signal.entry,
                stop_loss=signal.stop_loss,
                target=signal.target,
                mode=self.broker.mode,
                status="OPEN",
                broker_order_id=entry.order_id,
                entry_context=signal.context or {},
            )
            session.add(trade)
            session.add(
                AuditLog(
                    event="trade_opened",
                    payload={
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
            )
            session.commit()
            session.refresh(trade)
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
        with self._session_factory() as session:
            trade = session.get(Trade, trade_id)
            if trade is None or trade.status != "OPEN":
                return trade
            sign = 1 if trade.side == "BUY" else -1
            trade.exit_price = exit_price
            trade.pnl = round(sign * (exit_price - trade.entry_price) * trade.qty, 2)
            trade.status = "CLOSED"
            trade.closed_at = datetime.utcnow()
            session.add(
                AuditLog(
                    event="trade_closed",
                    payload={"trade_id": trade_id, "exit_price": exit_price, "pnl": trade.pnl},
                )
            )
            session.commit()
            session.refresh(trade)
            log.info("trade_closed", trade_id=trade_id, pnl=trade.pnl)
            return trade

    # ---------------------------------------------------------------------
    # Mark-to-market: auto-close open trades whose SL or target was hit.
    # Called on every scheduler tick with the latest price per symbol.
    # ---------------------------------------------------------------------
    def mark_to_market(self, latest_prices: dict[str, float], reason_tag: str = "mtm") -> list[Trade]:
        """For each OPEN trade in DB, close it if last price breached SL or target.

        Args:
            latest_prices: { symbol: last_close } dict from scheduler/Angel fetch
            reason_tag: included in the AuditLog payload for traceability

        Returns list of trades that were just closed.
        """
        closed: list[Trade] = []
        with self._session_factory() as session:
            open_trades = session.query(Trade).filter(Trade.status == "OPEN").all()
            for t in open_trades:
                last = latest_prices.get(t.symbol)
                if last is None:
                    continue

                reason: str | None = None
                if t.side == "BUY":
                    if last <= t.stop_loss:
                        reason = "stop_loss_hit"
                    elif t.target and last >= t.target:
                        reason = "target_hit"
                else:  # SELL
                    if last >= t.stop_loss:
                        reason = "stop_loss_hit"
                    elif t.target and last <= t.target:
                        reason = "target_hit"
                if reason is None:
                    continue

                sign = 1 if t.side == "BUY" else -1
                t.exit_price = last
                t.pnl = round(sign * (last - t.entry_price) * t.qty, 2)
                t.status = "CLOSED"
                t.closed_at = datetime.utcnow()
                session.add(
                    AuditLog(
                        event="trade_auto_closed",
                        payload={
                            "trade_id": t.id,
                            "symbol": t.symbol,
                            "side": t.side,
                            "exit_price": last,
                            "pnl": t.pnl,
                            "reason": reason,
                            "tag": reason_tag,
                        },
                    )
                )
                # Cancel SL leg on broker (best-effort; ignore failures)
                try:
                    if t.broker_order_id:
                        self.broker.cancel_order(t.broker_order_id + "-SL")
                except Exception:  # pragma: no cover
                    pass
                closed.append(t)
                log.info(
                    "trade_auto_closed",
                    trade_id=t.id, symbol=t.symbol, side=t.side,
                    exit_price=last, pnl=t.pnl, reason=reason,
                )
            if closed:
                session.commit()
                for t in closed:
                    session.refresh(t)
        return closed

    def force_close_all(self, latest_prices: dict[str, float], reason: str = "square_off") -> list[Trade]:
        """Close every OPEN trade at provided last price (EOD square-off)."""
        closed: list[Trade] = []
        with self._session_factory() as session:
            open_trades = session.query(Trade).filter(Trade.status == "OPEN").all()
            for t in open_trades:
                last = latest_prices.get(t.symbol, t.entry_price)
                sign = 1 if t.side == "BUY" else -1
                t.exit_price = last
                t.pnl = round(sign * (last - t.entry_price) * t.qty, 2)
                t.status = "CLOSED"
                t.closed_at = datetime.utcnow()
                session.add(
                    AuditLog(
                        event="trade_force_closed",
                        payload={"trade_id": t.id, "exit_price": last, "pnl": t.pnl, "reason": reason},
                    )
                )
                closed.append(t)
                log.info("trade_force_closed", trade_id=t.id, pnl=t.pnl, reason=reason)
            if closed:
                session.commit()
        return closed
