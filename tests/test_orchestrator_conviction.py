"""Tests for ensemble conviction logic in the orchestrator (Phase 3)."""

from __future__ import annotations

from app.engine.orchestrator import select_best_signal


# ---------------------------------------------------------------------------
# select_best_signal unit tests
# ---------------------------------------------------------------------------


def test_ensemble_blocks_when_only_one_strategy_fires(
    make_signal, make_settings
) -> None:
    """Single BUY signal with min_agreement=2 should return None."""
    signals = [
        make_signal(strategy="rsi_reversal", side="BUY", confidence=0.8, symbol="NIFTY")
    ]
    result = select_best_signal(
        signals, make_settings(min_strategy_agreement=2, min_signal_confidence=0.5)
    )
    assert result is None


def test_ensemble_passes_when_two_strategies_agree(make_signal, make_settings) -> None:
    """Two BUY signals from different strategies meet min_agreement=2."""
    signals = [
        make_signal(
            strategy="rsi_reversal", side="BUY", confidence=0.7, symbol="NIFTY"
        ),
        make_signal(
            strategy="ema_breakout", side="BUY", confidence=0.8, symbol="NIFTY"
        ),
    ]
    result = select_best_signal(
        signals, make_settings(min_strategy_agreement=2, min_signal_confidence=0.5)
    )
    assert result is not None
    assert result.side == "BUY"
    assert result.strategy == "ema_breakout"  # higher confidence


def test_ensemble_picks_highest_confidence(make_signal, make_settings) -> None:
    """Among 3 BUY signals, the one with highest confidence wins."""
    signals = [
        make_signal(
            strategy="rsi_reversal", side="BUY", confidence=0.55, symbol="NIFTY"
        ),
        make_signal(
            strategy="ema_breakout", side="BUY", confidence=0.65, symbol="NIFTY"
        ),
        make_signal(strategy="supertrend", side="BUY", confidence=0.90, symbol="NIFTY"),
    ]
    result = select_best_signal(
        signals, make_settings(min_strategy_agreement=2, min_signal_confidence=0.5)
    )
    assert result is not None
    assert result.strategy == "supertrend"
    assert result.confidence == 0.90


def test_low_confidence_signal_dropped(make_signal, make_settings) -> None:
    """Signals below min_signal_confidence are dropped before counting."""
    signals = [
        make_signal(
            strategy="rsi_reversal", side="BUY", confidence=0.3, symbol="NIFTY"
        ),  # below 0.5 threshold
        make_signal(
            strategy="ema_breakout", side="BUY", confidence=0.8, symbol="NIFTY"
        ),
    ]
    # Only 1 signal remains after dropping low-confidence, so it's < min_agreement=2
    result = select_best_signal(
        signals, make_settings(min_strategy_agreement=2, min_signal_confidence=0.5)
    )
    assert result is None


def test_conflicting_signals_picks_majority(make_signal, make_settings) -> None:
    """2 BUY + 1 SELL with min_agreement=2 → BUY wins."""
    signals = [
        make_signal(
            strategy="rsi_reversal", side="BUY", confidence=0.7, symbol="NIFTY"
        ),
        make_signal(
            strategy="ema_breakout", side="BUY", confidence=0.8, symbol="NIFTY"
        ),
        make_signal(strategy="supertrend", side="SELL", confidence=0.9, symbol="NIFTY"),
    ]
    result = select_best_signal(
        signals, make_settings(min_strategy_agreement=2, min_signal_confidence=0.5)
    )
    assert result is not None
    assert result.side == "BUY"
    assert result.strategy == "ema_breakout"  # highest BUY confidence


def test_single_strategy_mode_backward_compat(make_signal, make_settings) -> None:
    """min_agreement=1 should let any single signal through (POC behavior)."""
    signals = [
        make_signal(strategy="rsi_reversal", side="BUY", confidence=0.6, symbol="NIFTY")
    ]
    result = select_best_signal(
        signals, make_settings(min_strategy_agreement=1, min_signal_confidence=0.5)
    )
    assert result is not None
    assert result.strategy == "rsi_reversal"


def test_empty_signals_returns_none(make_settings) -> None:
    """No signals → None."""
    result = select_best_signal(
        [], make_settings(min_strategy_agreement=2, min_signal_confidence=0.5)
    )
    assert result is None


def test_all_below_confidence_returns_none(make_signal, make_settings) -> None:
    """All signals below min_signal_confidence → None."""
    signals = [
        make_signal(
            strategy="rsi_reversal", side="BUY", confidence=0.2, symbol="NIFTY"
        ),
        make_signal(
            strategy="ema_breakout", side="BUY", confidence=0.3, symbol="NIFTY"
        ),
    ]
    result = select_best_signal(signals, make_settings(min_signal_confidence=0.5))
    assert result is None


def test_tie_breaking_picks_higher_avg_confidence(make_signal, make_settings) -> None:
    """1 BUY (high conf) vs 1 SELL (low conf) with min_agreement=1 → BUY wins."""
    signals = [
        make_signal(
            strategy="rsi_reversal", side="BUY", confidence=0.9, symbol="NIFTY"
        ),
        make_signal(
            strategy="supertrend", side="SELL", confidence=0.55, symbol="NIFTY"
        ),
    ]
    result = select_best_signal(
        signals, make_settings(min_strategy_agreement=1, min_signal_confidence=0.5)
    )
    assert result is not None
    assert result.side == "BUY"


# ---------------------------------------------------------------------------
# Signal memory window tests
# ---------------------------------------------------------------------------


def _build_80bar_candles(make_candles):
    """Build 80 monotonically-declining bars (RSI deep oversold)."""
    import numpy as np

    return make_candles(closes=list(np.linspace(200, 100, 80)))


def test_signal_memory_merges_across_ticks(
    make_signal, make_settings, make_candles, db_factory, make_paper_broker
) -> None:
    """Signals from previous ticks should merge with current for conviction."""
    from unittest.mock import patch

    from app.engine.orchestrator import Orchestrator

    factory = db_factory()
    orch = Orchestrator(broker=make_paper_broker(), session_factory=factory)
    mem_settings = make_settings(
        min_strategy_agreement=2, min_signal_confidence=0.0, signal_memory_ticks=3
    )
    candles = _build_80bar_candles(make_candles)

    sig_a = make_signal(
        strategy="rsi_reversal", side="BUY", confidence=0.8, symbol="NIFTY"
    )
    sig_b = make_signal(
        strategy="ema_breakout", side="BUY", confidence=0.75, symbol="NIFTY"
    )

    with patch("app.engine.orchestrator.get_settings", return_value=mem_settings):
        orch.signal_agent.generate = lambda sym, c, **kw: [sig_a]
        outcomes_1 = orch.run("TEST", candles)

        orch.signal_agent.generate = lambda sym, c, **kw: [sig_b]
        outcomes_2 = orch.run("TEST", candles)

    assert len(outcomes_1) == 0  # only 1 strategy → no conviction
    assert len(outcomes_2) == 1  # memory merged both signals


def test_signal_memory_disabled_when_ticks_is_1(
    make_signal, make_settings, make_candles, db_factory, make_paper_broker
) -> None:
    """With signal_memory_ticks=1, only current-tick signals count."""
    from unittest.mock import patch

    from app.engine.orchestrator import Orchestrator

    factory = db_factory()
    orch = Orchestrator(broker=make_paper_broker(), session_factory=factory)
    no_mem_settings = make_settings(
        min_strategy_agreement=2, min_signal_confidence=0.0, signal_memory_ticks=1
    )
    candles = _build_80bar_candles(make_candles)

    sig_a = make_signal(
        strategy="rsi_reversal", side="BUY", confidence=0.8, symbol="NIFTY"
    )
    sig_b = make_signal(
        strategy="ema_breakout", side="BUY", confidence=0.75, symbol="NIFTY"
    )

    with patch("app.engine.orchestrator.get_settings", return_value=no_mem_settings):
        orch.signal_agent.generate = lambda sym, c, **kw: [sig_a]
        outcomes_1 = orch.run("TEST", candles)

        orch.signal_agent.generate = lambda sym, c, **kw: [sig_b]
        outcomes_2 = orch.run("TEST", candles)

    assert len(outcomes_1) == 0
    assert len(outcomes_2) == 0


def test_signal_memory_expires_old_signals(
    make_signal, make_settings, make_candles, db_factory, make_paper_broker
) -> None:
    """Signals older than the memory window should be pruned."""
    from unittest.mock import patch

    from app.engine.orchestrator import Orchestrator

    factory = db_factory()
    orch = Orchestrator(broker=make_paper_broker(), session_factory=factory)
    short_mem = make_settings(
        min_strategy_agreement=2, min_signal_confidence=0.0, signal_memory_ticks=2
    )
    candles = _build_80bar_candles(make_candles)

    sig_a = make_signal(
        strategy="rsi_reversal", side="BUY", confidence=0.8, symbol="NIFTY"
    )
    sig_b = make_signal(
        strategy="ema_breakout", side="BUY", confidence=0.75, symbol="NIFTY"
    )

    with patch("app.engine.orchestrator.get_settings", return_value=short_mem):
        orch.signal_agent.generate = lambda sym, c, **kw: [sig_a]
        orch.run("TEST", candles)

        orch.signal_agent.generate = lambda sym, c, **kw: []
        orch.run("TEST", candles)

        orch.signal_agent.generate = lambda sym, c, **kw: []
        orch.run("TEST", candles)

        orch.signal_agent.generate = lambda sym, c, **kw: [sig_b]
        outcomes = orch.run("TEST", candles)

    assert len(outcomes) == 0  # rsi expired, only ema remains
