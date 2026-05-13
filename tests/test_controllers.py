"""Unit tests for the thin controller layer.

These tests only assert delegation — business-logic behaviour is covered
in the matching service test module.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.controllers.execution_controller import ExecutionController
from app.controllers.signal_controller import SignalController
from app.controllers.trade_controller import TradeController
from app.controllers.validation_controller import ValidationController
from app.exceptions.domain import TradeNotFoundException
from app.models.trade import Trade


def test_signal_controller_delegates_to_service() -> None:
    svc = MagicMock()
    svc.generate.return_value = ["s1"]
    ctrl = SignalController(service=svc)
    assert ctrl.generate("X", "candles", "htf") == ["s1"]
    svc.generate.assert_called_once_with("X", "candles", "htf")


def test_validation_controller_delegates_to_service() -> None:
    svc = MagicMock()
    svc.validate.return_value = "validation"
    ctrl = ValidationController(service=svc)
    out = ctrl.validate(
        "sig", rag_context=["ctx"], regime="trend_up", corroborating_count=2
    )
    assert out == "validation"
    svc.validate.assert_called_once_with(
        "sig", rag_context=["ctx"], regime="trend_up", corroborating_count=2
    )


def test_execution_controller_delegates_all_methods() -> None:
    svc = MagicMock()
    ctrl = ExecutionController(service=svc)

    ctrl.execute("sig", qty=10, signal_row_id=42)
    svc.execute.assert_called_once_with("sig", 10, signal_row_id=42)

    ctrl.close_trade(7, 105.0)
    svc.close_trade.assert_called_once_with(7, 105.0)

    ctrl.mark_to_market({"X": 99.0}, reason_tag="live")
    svc.mark_to_market.assert_called_once_with({"X": 99.0}, reason_tag="live")

    ctrl.force_close_all({"X": 99.0}, reason="eod")
    svc.force_close_all.assert_called_once_with({"X": 99.0}, reason="eod")


def test_execution_controller_requires_broker_or_service() -> None:
    with pytest.raises(ValueError):
        ExecutionController()


def test_trade_controller_list_delegates_to_dal() -> None:
    dal = MagicMock()
    dal.list_recent.return_value = [
        Trade(
            id=1,
            symbol="A",
            side="BUY",
            qty=1,
            entry_price=1.0,
            stop_loss=1.0,
            mode="paper",
            status="OPEN",
        )
    ]
    ctrl = TradeController(dal=dal)
    rows = ctrl.list(limit=5)
    assert len(rows) == 1
    dal.list_recent.assert_called_once_with(limit=5)


def test_trade_controller_get_propagates_not_found() -> None:
    dal = MagicMock()
    dal.get_by_id.side_effect = TradeNotFoundException("trade 123 not found")
    ctrl = TradeController(dal=dal)
    with pytest.raises(TradeNotFoundException):
        ctrl.get(123)
