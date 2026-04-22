"""Unit tests for RiskEngine gates + position_size helper."""

from __future__ import annotations

from app.engine.risk_engine import position_size


def test_position_size_basic():
    # capital 100000, risk 1% = 1000; risk/unit = 2; qty = 500 with lot 1
    assert position_size(100_000, 1.0, 100.0, 98.0, lot_size=1) == 500


def test_position_size_rounds_down_to_lot():
    # 1000 budget / 2 per unit = 500; lot 75 -> 6 lots = 450
    assert position_size(100_000, 1.0, 100.0, 98.0, lot_size=75) == 450


def test_position_size_zero_on_bad_stop():
    assert position_size(100_000, 1.0, 100.0, 100.0) == 0


def test_kill_switch_blocks(make_risk_engine, make_signal):
    e = make_risk_engine(kill_switch=True)
    d = e.evaluate(make_signal())
    assert not d.approved and d.reason == "kill_switch_on"


def test_max_trades_per_day_blocks(make_risk_engine, make_signal):
    e = make_risk_engine()
    e.stats.trades_today = 5
    d = e.evaluate(make_signal())
    assert not d.approved and d.reason == "max_trades_per_day"


def test_max_open_positions_blocks(make_risk_engine, make_signal):
    e = make_risk_engine()
    e.stats.open_positions = 3
    d = e.evaluate(make_signal())
    assert not d.approved and d.reason == "max_open_positions"


def test_daily_loss_limit_blocks(make_risk_engine, make_signal):
    e = make_risk_engine()
    e.stats.realized_pnl_today = -2001
    d = e.evaluate(make_signal())
    assert not d.approved and d.reason == "daily_loss_limit"


def test_happy_path_approves_with_qty(make_risk_engine, make_signal):
    e = make_risk_engine()
    d = e.evaluate(make_signal(), lot_size=1)
    assert d.approved and d.qty == 500 and d.reason == "ok"
