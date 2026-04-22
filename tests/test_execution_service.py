"""Unit tests for :class:`app.services.execution_service.ExecutionService`."""
from __future__ import annotations

from app.dal.trade_dal import TradeDAL
from app.models.trade import AuditLog
from app.services.broker.base import OrderRequest, OrderResult
from app.services.execution_service import ExecutionService
from app.strategies.base import Signal


class _StubBroker:
    """Deterministic broker for ExecutionService unit tests."""

    mode = "paper"

    def __init__(self) -> None:
        self.orders: list[OrderRequest] = []
        self.cancelled: list[str] = []
        self._next_id = 0

    def place_order(self, req: OrderRequest) -> OrderResult:
        self.orders.append(req)
        self._next_id += 1
        return OrderResult(
            order_id=f"ORD-{self._next_id}",
            status="COMPLETE",
            avg_price=req.price or 100.0,
            filled_qty=req.qty,
        )

    def cancel_order(self, order_id: str) -> bool:
        self.cancelled.append(order_id)
        return True

    def get_quote(self, symbol: str) -> float:
        return 100.0


def _buy_signal(symbol: str = "X") -> Signal:
    return Signal(
        symbol=symbol,
        strategy="rsi_reversal",
        side="BUY",
        entry=100.0,
        stop_loss=98.0,
        target=104.0,
        confidence=0.7,
        context={"rsi": 22},
    )


def _svc(db_factory) -> tuple[ExecutionService, _StubBroker, TradeDAL]:
    factory = db_factory()
    broker = _StubBroker()
    dal = TradeDAL(session_factory=factory)
    return ExecutionService(broker, trade_dal=dal), broker, dal


def test_execute_places_entry_and_sl_and_persists_trade(db_factory) -> None:
    svc, broker, dal = _svc(db_factory)
    result = svc.execute(_buy_signal(), qty=10, signal_row_id=None)

    assert result.order_id.startswith("ORD-")
    opened = dal.find_open()
    assert len(opened) == 1
    t = opened[0]
    assert t.symbol == "X" and t.qty == 10 and t.status == "OPEN"
    assert t.broker_order_id == result.order_id
    # Broker received entry + SL leg.
    assert len(broker.orders) == 2
    assert broker.orders[0].order_type == "MARKET"
    assert broker.orders[1].order_type == "SL-M" and broker.orders[1].side == "SELL"


def test_execute_writes_trade_opened_audit_log(db_factory) -> None:
    svc, _, dal = _svc(db_factory)
    svc.execute(_buy_signal(), qty=5)

    with dal._session() as session:
        events = [r.event for r in session.query(AuditLog).all()]
    assert events == ["trade_opened"]


def test_close_trade_computes_pnl_and_writes_audit(db_factory) -> None:
    svc, _, dal = _svc(db_factory)
    svc.execute(_buy_signal(), qty=10)
    trade_id = dal.find_open()[0].id

    closed = svc.close_trade(trade_id, exit_price=105.0)
    assert closed is not None
    assert closed.status == "CLOSED"
    # BUY @100, exit @105, qty 10 → 50.0
    assert closed.pnl == 50.0


def test_close_trade_returns_none_when_missing(db_factory) -> None:
    svc, _, _ = _svc(db_factory)
    assert svc.close_trade(999, exit_price=100.0) is None


def test_mark_to_market_closes_on_stop_loss_buy(db_factory) -> None:
    svc, broker, dal = _svc(db_factory)
    svc.execute(_buy_signal("A"), qty=10)

    closed = svc.mark_to_market({"A": 97.0})  # below SL 98
    assert len(closed) == 1
    assert closed[0].pnl == -30.0  # (97-100) * 10
    assert dal.find_open() == []
    # SL leg cancellation best-effort
    assert any("-SL" in c for c in broker.cancelled)


def test_mark_to_market_closes_on_target_buy(db_factory) -> None:
    svc, _, _ = _svc(db_factory)
    svc.execute(_buy_signal("B"), qty=10)

    closed = svc.mark_to_market({"B": 105.0})  # above target 104
    assert len(closed) == 1 and closed[0].pnl == 50.0


def test_mark_to_market_ignores_untouched_trades(db_factory) -> None:
    svc, _, dal = _svc(db_factory)
    svc.execute(_buy_signal(), qty=10)

    closed = svc.mark_to_market({"X": 101.0})  # between SL & target
    assert closed == []
    assert len(dal.find_open()) == 1


def test_force_close_all_uses_entry_price_when_quote_missing(db_factory) -> None:
    svc, _, dal = _svc(db_factory)
    svc.execute(_buy_signal("Z"), qty=5)

    closed = svc.force_close_all({}, reason="eod")
    assert len(closed) == 1
    assert closed[0].pnl == 0.0  # exit == entry
    assert dal.find_open() == []


def test_breach_reason_sell_side() -> None:
    # SELL: SL above entry, target below entry
    assert ExecutionService._breach_reason("SELL", 105.0, 102.0, 95.0) == "stop_loss_hit"
    assert ExecutionService._breach_reason("SELL", 94.0, 102.0, 95.0) == "target_hit"
    assert ExecutionService._breach_reason("SELL", 100.0, 102.0, 95.0) is None
