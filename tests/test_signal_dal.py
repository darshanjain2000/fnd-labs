"""Unit tests for ``SignalDAL``."""

from __future__ import annotations

from datetime import datetime

import pytest

from app.dal.signal_dal import SignalDAL
from app.exceptions.domain import SignalNotFoundException
from app.models.trade import Signal


def _make_signal(symbol: str = "NIFTY", *, strategy: str = "rsi_reversal") -> Signal:
    return Signal(
        symbol=symbol,
        strategy=strategy,
        side="BUY",
        confidence=0.8,
        context={},
    )


def test_list_recent_orders_newest_first(db_factory) -> None:
    factory = db_factory()
    with factory() as s:
        older = _make_signal("A")
        older.created_at = datetime(2026, 1, 1)
        newer = _make_signal("B")
        newer.created_at = datetime(2026, 4, 1)
        s.add_all([older, newer])
        s.commit()

    rows = SignalDAL(session_factory=factory).list_recent()
    assert [r.symbol for r in rows] == ["B", "A"]


def test_get_by_id_raises_when_missing(db_factory) -> None:
    factory = db_factory()
    with pytest.raises(SignalNotFoundException):
        SignalDAL(session_factory=factory).get_by_id(1234)


def test_get_by_id_returns_row(db_factory) -> None:
    factory = db_factory()
    with factory() as s:
        sig = _make_signal("XYZ")
        s.add(sig)
        s.commit()
        sig_id = sig.id

    fetched = SignalDAL(session_factory=factory).get_by_id(sig_id)
    assert fetched.id == sig_id and fetched.symbol == "XYZ"
