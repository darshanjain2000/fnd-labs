"""End-to-end: orchestrator runs pipeline, Trade/Signal/AuditLog rows land in DB."""

from __future__ import annotations

from unittest.mock import patch

from app.engine.orchestrator import Orchestrator
from app.models.trade import AuditLog, Signal, Trade


def test_orchestrator_executes_and_persists_paper_trade(
    db_factory, make_paper_broker, make_settings, make_candles
):
    factory = db_factory()
    broker = make_paper_broker()
    orch = Orchestrator(broker=broker, session_factory=factory)

    with patch("app.engine.orchestrator.get_settings", return_value=make_settings()):
        outcomes = orch.run("TEST", make_candles())

    assert len(outcomes) >= 1
    executed = [o for o in outcomes if o.executed]
    assert executed, f"expected at least one executed outcome, got {outcomes}"
    o = executed[0]
    assert o.trade_id is not None
    assert o.order_id and o.order_id.startswith("PAPER-")
    assert o.signal_id is not None
    assert o.ai_approved is True  # LLM unavailable -> fallback approves high-confidence

    with factory() as session:
        trade = session.get(Trade, o.trade_id)
        assert trade is not None
        assert trade.status == "OPEN"
        assert trade.qty > 0
        assert trade.mode == "paper"
        assert trade.broker_order_id == o.order_id

        sig = session.get(Signal, o.signal_id)
        assert sig is not None
        assert sig.strategy in {"rsi_reversal", "ema_breakout", "vwap_pullback"}

        audits = session.query(AuditLog).filter(AuditLog.event == "trade_opened").all()
        assert len(audits) >= 1


def test_close_trade_computes_pnl(
    db_factory, make_paper_broker, make_settings, make_candles
):
    from app.agents.execution_agent import ExecutionAgent

    factory = db_factory()
    broker = make_paper_broker()
    orch = Orchestrator(broker=broker, session_factory=factory)
    with patch("app.engine.orchestrator.get_settings", return_value=make_settings()):
        outcomes = orch.run("TEST", make_candles())
    executed = next(o for o in outcomes if o.executed)

    agent = ExecutionAgent(broker, session_factory=factory)
    # For a BUY trade, exit > entry means profit.
    closed = agent.close_trade(executed.trade_id, exit_price=150.0)  # type: ignore[arg-type]
    assert closed is not None
    assert closed.status == "CLOSED"
    assert closed.exit_price == 150.0
    # side BUY: pnl = (exit - entry) * qty > 0 when exit > entry
    if closed.side == "BUY":
        assert closed.pnl > 0
    else:
        assert closed.pnl < 0
