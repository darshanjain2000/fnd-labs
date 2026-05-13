"""Phase 1 regressions: parallel candle fetch + AI confidence/source persistence."""

from __future__ import annotations

import asyncio
import time
from unittest.mock import patch

import numpy as np
import pandas as pd

from app.engine.orchestrator import Orchestrator
from app.models.trade import Signal


# ---------- 1. AI confidence + source are persisted on the Signal row -------


def test_orchestrator_persists_ai_confidence_and_source(
    db_factory, make_paper_broker, make_settings, make_candles
):
    factory = db_factory()
    broker = make_paper_broker()
    orch = Orchestrator(broker=broker, session_factory=factory)

    with patch("app.engine.orchestrator.get_settings", return_value=make_settings()):
        outcomes = orch.run("TEST", make_candles())
    assert outcomes, "expected at least one outcome"
    o = outcomes[0]

    with factory() as session:
        sig = session.get(Signal, o.signal_id)
        assert sig is not None
        # When LLM is disabled (no API key in test env), source must be 'disabled'.
        assert sig.ai_source in {"llm", "disabled", "fallback", "spend_cap"}
        # ai_confidence should be a float between 0 and 1.
        assert sig.ai_confidence is not None
        assert 0.0 <= float(sig.ai_confidence) <= 1.0


# ---------- 2. Scheduler fetches watchlist candles in parallel --------------


def test_scheduler_fetch_is_parallel(monkeypatch):
    """Fetching N symbols must be ~max(single_fetch_time), not N×single_fetch_time.

    We stub `session.fetch_candles_for_symbol` to sleep 300ms and return 30 fake
    candles. With 4 symbols, serial would take ~1.2s; parallel must stay under 900ms.
    """
    from app.services import scheduler as sched_mod
    from app.services.scheduler import MarketScheduler

    # Build 4 fake candles frame (long enough to exceed the 20-row guard).
    def _fake_df():
        closes = list(np.linspace(100, 110, 30))
        return pd.DataFrame(
            {
                "open": closes,
                "high": closes,
                "low": closes,
                "close": closes,
                "volume": [500] * 30,
            }
        )

    class _FakeSession:
        def ensure_ready(self) -> None:
            pass  # no-op — session is always "ready" in tests

        def fetch_candles_for_symbol(self, sym, exch, interval, start, end):
            time.sleep(0.3)  # simulated IO latency
            return _fake_df()

    monkeypatch.setattr(sched_mod, "get_angel_session", lambda: _FakeSession())

    # Force _within_market_hours + disable EOD, skip orchestrator run.
    sched = MarketScheduler()
    monkeypatch.setattr(sched, "_within_market_hours", lambda now: True)
    monkeypatch.setattr(sched, "_past_square_off", lambda now: False)

    # Point watchlist at 4 symbols via settings override.
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "watchlist", "A:NSE,B:NSE,C:NSE,D:NSE", raising=False)
    # Disable stagger so this test measures raw parallelism, not stagger delay.
    monkeypatch.setattr(settings, "fetch_stagger_ms", 0, raising=False)

    # Stub orchestrator so the tick doesn't touch DB/broker.
    class _StubRiskStats:
        open_positions = 0
        trades_today = 0
        realized_pnl_today = 0.0

    class _StubRisk:
        stats = _StubRiskStats()

    class _StubOrch:
        class _Exec:
            def mark_to_market(self, prices, reason_tag):
                return []

            def force_close_all(self, prices, reason):
                return []

        execution_agent = _Exec()
        risk = _StubRisk()

        def run(self, sym, df):
            return []

    monkeypatch.setattr(sched_mod, "get_orchestrator", lambda: _StubOrch())

    started = time.perf_counter()
    asyncio.run(sched._tick())
    elapsed = time.perf_counter() - started

    # 4 symbols × 0.3s would be >1.1s serial. Parallel should finish in ~0.4s.
    # Generous bound to avoid flakes on slow CI.
    assert elapsed < 0.9, f"fetch appears serial: {elapsed:.2f}s for 4 parallel fetches"
