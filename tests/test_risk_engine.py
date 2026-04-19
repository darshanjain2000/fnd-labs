from app.config import Settings
from app.engine.risk_engine import RiskEngine, position_size
from app.strategies.base import Signal


def _sig(entry=100.0, stop=98.0) -> Signal:
    return Signal(symbol="X", strategy="t", side="BUY", entry=entry, stop_loss=stop, target=104.0)


def test_position_size_basic():
    # capital 100000, risk 1% = 1000; risk/unit = 2; qty = 500 with lot 1
    assert position_size(100_000, 1.0, 100.0, 98.0, lot_size=1) == 500


def test_position_size_rounds_down_to_lot():
    # 1000 budget / 2 per unit = 500; lot 75 -> 6 lots = 450
    assert position_size(100_000, 1.0, 100.0, 98.0, lot_size=75) == 450


def test_position_size_zero_on_bad_stop():
    assert position_size(100_000, 1.0, 100.0, 100.0) == 0


def _engine(**overrides) -> RiskEngine:
    base = dict(
        mode="paper", capital_inr=100_000.0, max_risk_per_trade_pct=1.0,
        max_daily_loss_pct=2.0, max_open_positions=3, max_trades_per_day=5,
        kill_switch=False, block_expiry_last_hours=2,
    )
    base.update(overrides)
    return RiskEngine(settings=Settings(**base))


def test_kill_switch_blocks():
    e = _engine(kill_switch=True)
    d = e.evaluate(_sig())
    assert not d.approved and d.reason == "kill_switch_on"


def test_max_trades_per_day_blocks():
    e = _engine()
    e.stats.trades_today = 5
    d = e.evaluate(_sig())
    assert not d.approved and d.reason == "max_trades_per_day"


def test_max_open_positions_blocks():
    e = _engine()
    e.stats.open_positions = 3
    d = e.evaluate(_sig())
    assert not d.approved and d.reason == "max_open_positions"


def test_daily_loss_limit_blocks():
    e = _engine()
    e.stats.realized_pnl_today = -2001
    d = e.evaluate(_sig())
    assert not d.approved and d.reason == "daily_loss_limit"


def test_happy_path_approves_with_qty():
    e = _engine()
    d = e.evaluate(_sig(), lot_size=1)
    assert d.approved and d.qty == 500 and d.reason == "ok"
