"""Scheduler: unit tests that don't hit the network or Angel SDK."""
from __future__ import annotations

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import pytest

from app.services.scheduler import MarketScheduler

IST = ZoneInfo("Asia/Kolkata")


def test_within_market_hours_weekday_open():
    sched = MarketScheduler()
    # Monday 10:00 IST
    now = datetime(2026, 4, 20, 10, 0, tzinfo=IST)
    assert sched._within_market_hours(now) is True


def test_within_market_hours_weekend():
    sched = MarketScheduler()
    # Saturday
    now = datetime(2026, 4, 18, 10, 0, tzinfo=IST)
    assert sched._within_market_hours(now) is False


def test_within_market_hours_after_close():
    sched = MarketScheduler()
    now = datetime(2026, 4, 20, 16, 0, tzinfo=IST)
    assert sched._within_market_hours(now) is False


def test_past_square_off():
    sched = MarketScheduler()
    assert sched._past_square_off(datetime(2026, 4, 20, 15, 21, tzinfo=IST)) is True
    assert sched._past_square_off(datetime(2026, 4, 20, 15, 19, tzinfo=IST)) is False


def test_report_day_window_boundary():
    """IST day 00:00-23:59 converts to a non-empty UTC window."""
    from app.api.runner import _ist_day_window
    start, end = _ist_day_window(date(2026, 4, 20))
    # 00:00 IST = 18:30 UTC previous day
    assert start.hour == 18 and start.minute == 30
    # 23:59 IST = 18:29 UTC same day
    assert end.hour == 18 and end.minute == 29


def test_mark_to_market_closes_hit_trade():
    """Full DB round-trip on the configured DB using a unique test symbol."""
    import uuid
    from app.db import SessionLocal, init_db
    from app.agents.execution_agent import ExecutionAgent
    from app.models.trade import Trade
    from app.services.broker.paper_broker import PaperBroker

    init_db()
    sym = f"TESTX-{uuid.uuid4().hex[:8]}"
    broker = PaperBroker(quote_fn=lambda s: 100.0)
    agent = ExecutionAgent(broker)

    # Seed an open SELL trade: entry=100, SL=105
    with SessionLocal() as session:
        t = Trade(
            symbol=sym, strategy="rsi_reversal", side="SELL", qty=10,
            entry_price=100.0, stop_loss=105.0, target=95.0,
            mode="paper", status="OPEN", broker_order_id=f"TEST-{sym}",
            entry_context={},
        )
        session.add(t)
        session.commit()

    # Below SL — should NOT close
    closed = agent.mark_to_market({sym: 102.0})
    assert not any(c.symbol == sym for c in closed)

    # Above SL — should close with loss
    closed = agent.mark_to_market({sym: 106.0})
    hit = [c for c in closed if c.symbol == sym]
    assert len(hit) == 1
    assert hit[0].status == "CLOSED"
    # SELL entry=100, exit=106 → pnl = -1 * (106 - 100) * 10 = -60
    assert hit[0].pnl == -60.0
