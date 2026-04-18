"""End-to-end: orchestrator runs pipeline, Trade/Signal/AuditLog rows land in DB."""
from __future__ import annotations

import numpy as np
import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.engine.orchestrator import Orchestrator
from app.models import Base
from app.models.trade import AuditLog, Signal, Trade
from app.services.broker.paper_broker import PaperBroker
from app.services.market_data import compute_indicators


def _make_db_factory():
    engine = create_engine("sqlite:///:memory:", future=True, connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def _oversold_candles() -> pd.DataFrame:
    closes = list(np.linspace(200, 100, 60))  # monotonic decline -> RSI deep oversold
    df = pd.DataFrame({
        "open": closes,
        "high": [c * 1.005 for c in closes],
        "low": [c * 0.995 for c in closes],
        "close": closes,
        "volume": [1000] * len(closes),
    })
    return compute_indicators(df)


def test_orchestrator_executes_and_persists_paper_trade():
    factory = _make_db_factory()
    broker = PaperBroker(quote_fn=lambda s: 100.0)
    orch = Orchestrator(broker=broker, session_factory=factory)

    outcomes = orch.run("TEST", _oversold_candles())

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


def test_close_trade_computes_pnl():
    from app.agents.execution_agent import ExecutionAgent

    factory = _make_db_factory()
    broker = PaperBroker(quote_fn=lambda s: 100.0)
    orch = Orchestrator(broker=broker, session_factory=factory)
    outcomes = orch.run("TEST", _oversold_candles())
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
