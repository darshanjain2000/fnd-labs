"""Unit tests for ``TradeDAL``."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app.dal.trade_dal import TradeDAL
from app.exceptions.domain import TradeNotFoundException
from app.models.trade import Trade


def _make_trade(
    symbol: str = "RELIANCE",
    *,
    status: str = "OPEN",
    side: str = "BUY",
    strategy: str = "rsi_reversal",
    broker_order_id: str | None = None,
    pnl: float = 0.0,
    opened_at: datetime | None = None,
    closed_at: datetime | None = None,
) -> Trade:
    return Trade(
        symbol=symbol,
        strategy=strategy,
        side=side,
        qty=10,
        entry_price=100.0,
        stop_loss=98.0,
        target=104.0,
        pnl=pnl,
        mode="paper",
        status=status,
        broker_order_id=broker_order_id,
        entry_context={},
        opened_at=opened_at or datetime.utcnow(),
        closed_at=closed_at,
    )


def test_list_recent_returns_newest_first(db_factory) -> None:
    factory = db_factory()
    with factory() as s:
        older = _make_trade(opened_at=datetime(2026, 1, 1))
        newer = _make_trade(opened_at=datetime(2026, 4, 1))
        s.add_all([older, newer])
        s.commit()

    rows = TradeDAL(session_factory=factory).list_recent(limit=10)
    assert len(rows) == 2
    assert rows[0].opened_at > rows[1].opened_at


def test_get_by_id_raises_when_missing(db_factory) -> None:
    factory = db_factory()
    with pytest.raises(TradeNotFoundException):
        TradeDAL(session_factory=factory).get_by_id(999)


def test_find_by_id_returns_none_when_missing(db_factory) -> None:
    factory = db_factory()
    assert TradeDAL(session_factory=factory).find_by_id(999) is None


def test_find_open_filters_on_status(db_factory) -> None:
    factory = db_factory()
    with factory() as s:
        s.add_all(
            [
                _make_trade(status="OPEN"),
                _make_trade(status="CLOSED"),
                _make_trade(status="OPEN"),
            ]
        )
        s.commit()

    rows = TradeDAL(session_factory=factory).find_open()
    assert len(rows) == 2
    assert all(r.status == "OPEN" for r in rows)


def test_list_open_symbols_returns_distinct_symbols(db_factory) -> None:
    factory = db_factory()
    with factory() as s:
        s.add_all(
            [
                _make_trade(symbol="AAA", status="OPEN"),
                _make_trade(symbol="BBB", status="OPEN"),
                _make_trade(symbol="AAA", status="OPEN"),  # duplicate
                _make_trade(symbol="CCC", status="CLOSED"),  # filtered out
            ]
        )
        s.commit()

    syms = set(TradeDAL(session_factory=factory).list_open_symbols())
    assert syms == {"AAA", "BBB"}


def test_find_by_broker_order_id_matches(db_factory) -> None:
    factory = db_factory()
    with factory() as s:
        t = _make_trade(broker_order_id="ORD-42")
        s.add(t)
        s.commit()
        expected_id = t.id

    dal = TradeDAL(session_factory=factory)
    assert dal.find_by_broker_order_id("ORD-42") == expected_id
    assert dal.find_by_broker_order_id("ORD-missing") is None


def test_find_closed_by_symbol_orders_newest_first(db_factory) -> None:
    factory = db_factory()
    base = datetime(2026, 4, 1)
    with factory() as s:
        s.add_all(
            [
                _make_trade(
                    symbol="X", status="CLOSED", closed_at=base + timedelta(days=1)
                ),
                _make_trade(
                    symbol="X", status="CLOSED", closed_at=base + timedelta(days=3)
                ),
                _make_trade(
                    symbol="X", status="CLOSED", closed_at=base + timedelta(days=2)
                ),
                _make_trade(
                    symbol="Y", status="CLOSED", closed_at=base + timedelta(days=5)
                ),
            ]
        )
        s.commit()

    rows = TradeDAL(session_factory=factory).find_closed_by_symbol("X", limit=10)
    assert [r.symbol for r in rows] == ["X", "X", "X"]
    assert rows[0].closed_at > rows[1].closed_at > rows[2].closed_at


def test_find_closed_by_symbol_applies_filters(db_factory) -> None:
    factory = db_factory()
    with factory() as s:
        s.add_all(
            [
                _make_trade(
                    symbol="Z", status="CLOSED", side="BUY", strategy="rsi_reversal"
                ),
                _make_trade(
                    symbol="Z", status="CLOSED", side="SELL", strategy="rsi_reversal"
                ),
                _make_trade(
                    symbol="Z", status="CLOSED", side="BUY", strategy="ema_breakout"
                ),
            ]
        )
        s.commit()

    dal = TradeDAL(session_factory=factory)
    rows = dal.find_closed_by_symbol("Z", strategy="rsi_reversal", side="BUY")
    assert len(rows) == 1
    assert rows[0].strategy == "rsi_reversal" and rows[0].side == "BUY"
