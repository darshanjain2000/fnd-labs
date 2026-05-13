"""Scheduler: unit tests that don't hit the network or Angel SDK."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo


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


def test_within_market_hours_respects_config_window() -> None:
    """Scheduler should honor configured market_open and market_close values."""
    from app.config import Settings

    sched = MarketScheduler()
    now = datetime(2026, 4, 20, 9, 30, tzinfo=IST)
    custom = Settings(market_open="10:00", market_close="11:00")
    with patch("app.services.scheduler.get_settings", return_value=custom):
        assert sched._within_market_hours(now) is False


def test_past_square_off():
    sched = MarketScheduler()
    assert sched._past_square_off(datetime(2026, 4, 20, 15, 21, tzinfo=IST)) is True
    assert sched._past_square_off(datetime(2026, 4, 20, 15, 19, tzinfo=IST)) is False


def test_describe_next_open_skips_holiday() -> None:
    """Next-open descriptor should skip configured NSE holidays."""
    sched = MarketScheduler()
    # Jan 25, 2026 is Sunday; Jan 26 holiday, so next open is Jan 27.
    now = datetime(2026, 1, 25, 10, 0, tzinfo=IST)
    msg = sched._describe_next_open(now)
    assert "Tue 27 Jan 09:15 IST" in msg


def test_report_day_window_boundary():
    """IST day 00:00-23:59 converts to a non-empty UTC window."""
    from app.routers.report_router import _ist_day_window

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
            symbol=sym,
            strategy="rsi_reversal",
            side="SELL",
            qty=10,
            entry_price=100.0,
            stop_loss=105.0,
            target=95.0,
            mode="paper",
            status="OPEN",
            broker_order_id=f"TEST-{sym}",
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


# ---- Heartbeat tests --------------------------------------------------------


def _make_scheduler_with_status(started_at: datetime) -> MarketScheduler:
    """Return a MarketScheduler whose status reflects an already-started run."""
    sched = MarketScheduler()
    sched.status.running = True
    sched.status.started_at = started_at
    sched.status.ticks = 5
    sched.status.signals_seen = 3
    sched.status.trades_opened = 1
    return sched


def _mock_orchestrator(
    open_positions: int = 2, trades_today: int = 3, pnl: float = 500.0
) -> MagicMock:
    """Return a mock orchestrator whose risk.stats carry the given values."""
    orch = MagicMock()
    orch.risk.stats.open_positions = open_positions
    orch.risk.stats.trades_today = trades_today
    orch.risk.stats.realized_pnl_today = pnl
    return orch


def test_heartbeat_fires_on_first_call() -> None:
    """Heartbeat must fire immediately on the first call (no prior timestamp)."""
    IST = ZoneInfo("Asia/Kolkata")
    started = datetime(2026, 4, 20, 9, 15, tzinfo=IST)
    now = datetime(2026, 4, 20, 9, 20, tzinfo=IST)  # 5 min after start
    sched = _make_scheduler_with_status(started)

    with patch(
        "app.services.scheduler.get_orchestrator", return_value=_mock_orchestrator()
    ):
        with patch("app.services.scheduler.log") as mock_log:
            sched._maybe_log_heartbeat(now)
            mock_log.info.assert_called_once_with(
                "scheduler_heartbeat",
                tick=5,
                open_positions=2,
                trades_today=3,
                realized_pnl=500.0,
                signals_seen=3,
                uptime="0h 5m",
            )


def test_heartbeat_skips_within_interval() -> None:
    """Second call within LOG_HEARTBEAT_INTERVAL_SEC must not emit a log."""
    IST = ZoneInfo("Asia/Kolkata")
    started = datetime(2026, 4, 20, 9, 15, tzinfo=IST)
    first = datetime(2026, 4, 20, 9, 20, tzinfo=IST)
    second = first + timedelta(seconds=60)  # default interval is 300s; 60s < 300s

    sched = _make_scheduler_with_status(started)

    with patch(
        "app.services.scheduler.get_orchestrator", return_value=_mock_orchestrator()
    ):
        with patch("app.services.scheduler.log") as mock_log:
            sched._maybe_log_heartbeat(first)
            sched._maybe_log_heartbeat(second)
            assert mock_log.info.call_count == 1  # only the first call should log


def test_heartbeat_fires_again_after_interval_elapsed() -> None:
    """Third call after the full interval must emit a second heartbeat log."""
    IST = ZoneInfo("Asia/Kolkata")
    started = datetime(2026, 4, 20, 9, 15, tzinfo=IST)
    first = datetime(2026, 4, 20, 9, 20, tzinfo=IST)
    second = first + timedelta(seconds=301)  # > 300s default interval

    sched = _make_scheduler_with_status(started)

    with patch(
        "app.services.scheduler.get_orchestrator", return_value=_mock_orchestrator()
    ):
        with patch("app.services.scheduler.log") as mock_log:
            sched._maybe_log_heartbeat(first)
            sched._maybe_log_heartbeat(second)
            assert mock_log.info.call_count == 2


def test_heartbeat_disabled_when_interval_is_zero() -> None:
    """Setting LOG_HEARTBEAT_INTERVAL_SEC=0 must suppress all heartbeat logs."""
    from app.config import Settings

    IST = ZoneInfo("Asia/Kolkata")
    started = datetime(2026, 4, 20, 9, 15, tzinfo=IST)
    now = datetime(2026, 4, 20, 9, 20, tzinfo=IST)
    sched = _make_scheduler_with_status(started)

    disabled_settings = Settings(log_heartbeat_interval_sec=0)
    with patch("app.services.scheduler.get_settings", return_value=disabled_settings):
        with patch("app.services.scheduler.log") as mock_log:
            sched._maybe_log_heartbeat(now)
            mock_log.info.assert_not_called()
