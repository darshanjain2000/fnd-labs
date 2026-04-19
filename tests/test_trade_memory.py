"""TradeMemory: SQL-backed replacement for RAG context."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.memory.trade_memory import TradeMemory
from app.models import Base
from app.models.trade import Trade


def _make_factory():
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def _seed(factory, rows: list[dict]) -> None:
    with factory() as s:
        for r in rows:
            s.add(
                Trade(
                    opened_at=datetime.utcnow(),
                    closed_at=datetime.utcnow(),
                    status="CLOSED",
                    mode="paper",
                    symbol=r["symbol"],
                    strategy=r["strategy"],
                    side=r["side"],
                    qty=r.get("qty", 50),
                    entry_price=r.get("entry_price", 100.0),
                    exit_price=r.get("exit_price", 110.0),
                    stop_loss=r.get("stop_loss", 95.0),
                    target=r.get("target", 120.0),
                    pnl=r["pnl"],
                )
            )
        s.commit()


def test_stats_aggregates_wins_losses_and_avg_pnl():
    factory = _make_factory()
    _seed(factory, [
        {"symbol": "NIFTY", "strategy": "rsi_reversal", "side": "BUY", "pnl": 300.0},
        {"symbol": "NIFTY", "strategy": "rsi_reversal", "side": "BUY", "pnl": -100.0},
        {"symbol": "NIFTY", "strategy": "rsi_reversal", "side": "BUY", "pnl": 200.0},
        {"symbol": "NIFTY", "strategy": "ema_breakout", "side": "BUY", "pnl": 500.0},  # filtered out
    ])
    mem = TradeMemory(session_factory=factory)
    stats = mem.stats("NIFTY", "rsi_reversal", "BUY")
    assert stats.total == 3
    assert stats.wins == 2
    assert stats.losses == 1
    assert round(stats.win_rate, 2) == 0.67
    assert round(stats.avg_pnl, 2) == round((300 - 100 + 200) / 3, 2)


def test_format_context_returns_history_line_and_rows():
    factory = _make_factory()
    _seed(factory, [
        {"symbol": "BANKNIFTY", "strategy": "ema_breakout", "side": "BUY", "pnl": 400.0},
        {"symbol": "BANKNIFTY", "strategy": "ema_breakout", "side": "BUY", "pnl": -200.0},
    ])
    mem = TradeMemory(session_factory=factory)
    lines = mem.format_context("BANKNIFTY", "ema_breakout", "BUY", k=5)
    assert lines, "expected at least one context line"
    assert any("History[" in l for l in lines)
    assert any("Past:" in l for l in lines)


def test_recent_similar_excludes_open_trades_and_other_symbols():
    factory = _make_factory()
    _seed(factory, [
        {"symbol": "NIFTY", "strategy": "rsi_reversal", "side": "BUY", "pnl": 100.0},
    ])
    # Also add an OPEN trade — must be excluded.
    with factory() as s:
        s.add(Trade(
            opened_at=datetime.utcnow(), status="OPEN", mode="paper",
            symbol="NIFTY", strategy="rsi_reversal", side="BUY",
            qty=50, entry_price=100, stop_loss=95, pnl=0.0,
        ))
        s.commit()
    mem = TradeMemory(session_factory=factory)
    rows = mem.recent_similar("NIFTY", "rsi_reversal", "BUY", k=10)
    assert len(rows) == 1
    assert rows[0]["symbol"] == "NIFTY"


def test_no_history_returns_empty_list():
    factory = _make_factory()
    mem = TradeMemory(session_factory=factory)
    assert mem.format_context("FOO", "rsi_reversal", "BUY") == []
    stats = mem.stats("FOO", "rsi_reversal", "BUY")
    assert stats.total == 0
    assert stats.win_rate == 0.0
