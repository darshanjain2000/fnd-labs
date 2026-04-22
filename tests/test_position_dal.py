"""Unit tests for ``PositionDAL``."""
from __future__ import annotations

from app.dal.position_dal import PositionDAL
from app.models.trade import Position


def test_get_by_symbol_returns_none_when_missing(db_factory) -> None:
    factory = db_factory()
    assert PositionDAL(session_factory=factory).get_by_symbol("NONEXIST") is None


def test_get_by_symbol_returns_row(db_factory) -> None:
    factory = db_factory()
    with factory() as s:
        s.add(Position(symbol="RELIANCE", qty=50, avg_price=100.0))
        s.commit()

    pos = PositionDAL(session_factory=factory).get_by_symbol("RELIANCE")
    assert pos is not None and pos.symbol == "RELIANCE" and pos.qty == 50


def test_get_net_position_returns_zero_when_missing(db_factory) -> None:
    factory = db_factory()
    assert PositionDAL(session_factory=factory).get_net_position("NONE") == 0


def test_get_net_position_returns_signed_qty(db_factory) -> None:
    factory = db_factory()
    with factory() as s:
        s.add_all(
            [
                Position(symbol="LONG", qty=25, avg_price=100.0),
                Position(symbol="SHORT", qty=-10, avg_price=50.0),
            ]
        )
        s.commit()

    dal = PositionDAL(session_factory=factory)
    assert dal.get_net_position("LONG") == 25
    assert dal.get_net_position("SHORT") == -10
