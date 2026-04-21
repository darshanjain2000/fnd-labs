"""Tests for ensemble conviction logic in the orchestrator (Phase 3)."""
from __future__ import annotations

from app.config import Settings
from app.engine.orchestrator import select_best_signal
from app.strategies.base import Signal


def _sig(
    strategy: str = "strat_a",
    side: str = "BUY",
    confidence: float = 0.7,
    symbol: str = "NIFTY",
) -> Signal:
    """Build a minimal Signal for testing.

    Args:
        strategy: Strategy name.
        side: "BUY" or "SELL".
        confidence: Strategy confidence in [0, 1].
        symbol: Trading symbol.

    Returns:
        Signal instance.
    """
    return Signal(
        symbol=symbol,
        strategy=strategy,
        side=side,
        entry=100.0,
        stop_loss=98.0,
        target=104.0,
        confidence=confidence,
    )


def _settings(**overrides) -> Settings:
    """Build a Settings instance with test defaults.

    Args:
        **overrides: Fields to override on the base Settings.

    Returns:
        Settings instance.
    """
    base = dict(
        mode="paper",
        min_strategy_agreement=2,
        min_signal_confidence=0.5,
    )
    base.update(overrides)
    return Settings(**base)


# ---------------------------------------------------------------------------
# select_best_signal unit tests
# ---------------------------------------------------------------------------


def test_ensemble_blocks_when_only_one_strategy_fires() -> None:
    """Single BUY signal with min_agreement=2 should return None."""
    signals = [_sig("rsi_reversal", "BUY", 0.8)]
    result = select_best_signal(signals, _settings(min_strategy_agreement=2))
    assert result is None


def test_ensemble_passes_when_two_strategies_agree() -> None:
    """Two BUY signals from different strategies meet min_agreement=2."""
    signals = [
        _sig("rsi_reversal", "BUY", 0.7),
        _sig("ema_breakout", "BUY", 0.8),
    ]
    result = select_best_signal(signals, _settings(min_strategy_agreement=2))
    assert result is not None
    assert result.side == "BUY"
    assert result.strategy == "ema_breakout"  # higher confidence


def test_ensemble_picks_highest_confidence() -> None:
    """Among 3 BUY signals, the one with highest confidence wins."""
    signals = [
        _sig("rsi_reversal", "BUY", 0.55),
        _sig("ema_breakout", "BUY", 0.65),
        _sig("supertrend", "BUY", 0.90),
    ]
    result = select_best_signal(signals, _settings(min_strategy_agreement=2))
    assert result is not None
    assert result.strategy == "supertrend"
    assert result.confidence == 0.90


def test_low_confidence_signal_dropped() -> None:
    """Signals below min_signal_confidence are dropped before counting."""
    signals = [
        _sig("rsi_reversal", "BUY", 0.3),  # below 0.5 threshold
        _sig("ema_breakout", "BUY", 0.8),
    ]
    # Only 1 signal remains after dropping low-confidence, so it's < min_agreement=2
    result = select_best_signal(signals, _settings(min_strategy_agreement=2, min_signal_confidence=0.5))
    assert result is None


def test_conflicting_signals_picks_majority() -> None:
    """2 BUY + 1 SELL with min_agreement=2 → BUY wins."""
    signals = [
        _sig("rsi_reversal", "BUY", 0.7),
        _sig("ema_breakout", "BUY", 0.8),
        _sig("supertrend", "SELL", 0.9),
    ]
    result = select_best_signal(signals, _settings(min_strategy_agreement=2))
    assert result is not None
    assert result.side == "BUY"
    assert result.strategy == "ema_breakout"  # highest BUY confidence


def test_single_strategy_mode_backward_compat() -> None:
    """min_agreement=1 should let any single signal through (POC behavior)."""
    signals = [_sig("rsi_reversal", "BUY", 0.6)]
    result = select_best_signal(signals, _settings(min_strategy_agreement=1))
    assert result is not None
    assert result.strategy == "rsi_reversal"


def test_empty_signals_returns_none() -> None:
    """No signals → None."""
    result = select_best_signal([], _settings())
    assert result is None


def test_all_below_confidence_returns_none() -> None:
    """All signals below min_signal_confidence → None."""
    signals = [
        _sig("rsi_reversal", "BUY", 0.2),
        _sig("ema_breakout", "BUY", 0.3),
    ]
    result = select_best_signal(signals, _settings(min_signal_confidence=0.5))
    assert result is None


def test_tie_breaking_picks_higher_avg_confidence() -> None:
    """1 BUY (high conf) vs 1 SELL (low conf) with min_agreement=1 → BUY wins."""
    signals = [
        _sig("rsi_reversal", "BUY", 0.9),
        _sig("supertrend", "SELL", 0.55),
    ]
    result = select_best_signal(signals, _settings(min_strategy_agreement=1))
    assert result is not None
    assert result.side == "BUY"

# ---------------------------------------------------------------------------
# Signal memory window tests
# ---------------------------------------------------------------------------

def test_signal_memory_merges_across_ticks() -> None:
    """Signals from previous ticks should merge with current for conviction."""
    from unittest.mock import patch

    import numpy as np
    import pandas as pd

    from app.engine.orchestrator import Orchestrator
    from app.models import Base
    from app.services.broker.paper_broker import PaperBroker
    from app.services.market_data import compute_indicators
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine("sqlite:///:memory:", future=True, connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    broker = PaperBroker(quote_fn=lambda s: 100.0)
    orch = Orchestrator(broker=broker, session_factory=factory)

    # Settings: need 2 strategies, memory_ticks=3
    mem_settings = Settings(
        mode="paper", min_strategy_agreement=2, min_signal_confidence=0.0,
        signal_memory_ticks=3,
    )

    # Build candle data
    closes = list(np.linspace(200, 100, 80))
    df = pd.DataFrame({
        "open": closes,
        "high": [c * 1.005 for c in closes],
        "low": [c * 0.995 for c in closes],
        "close": closes,
        "volume": [1000] * len(closes),
    })
    candles = compute_indicators(df)

    # Mock signal_agent to return different single strategies on different ticks
    sig_a = _sig("rsi_reversal", "BUY", 0.8)
    sig_b = _sig("ema_breakout", "BUY", 0.75)

    with patch("app.engine.orchestrator.get_settings", return_value=mem_settings):
        # Tick 1: only rsi_reversal fires → no conviction (need 2)
        orch.signal_agent.generate = lambda sym, c, **kw: [sig_a]
        outcomes_1 = orch.run("TEST", candles)

        # Tick 2: only ema_breakout fires → buffer now has both → conviction!
        orch.signal_agent.generate = lambda sym, c, **kw: [sig_b]
        outcomes_2 = orch.run("TEST", candles)

    # Tick 1 should have no trade (only 1 strategy)
    assert len(outcomes_1) == 0
    # Tick 2 should have a trade (memory merged both signals)
    assert len(outcomes_2) == 1


def test_signal_memory_disabled_when_ticks_is_1() -> None:
    """With signal_memory_ticks=1, only current-tick signals count."""
    from unittest.mock import patch

    import numpy as np
    import pandas as pd

    from app.engine.orchestrator import Orchestrator
    from app.models import Base
    from app.services.broker.paper_broker import PaperBroker
    from app.services.market_data import compute_indicators
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine("sqlite:///:memory:", future=True, connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    broker = PaperBroker(quote_fn=lambda s: 100.0)
    orch = Orchestrator(broker=broker, session_factory=factory)

    no_mem_settings = Settings(
        mode="paper", min_strategy_agreement=2, min_signal_confidence=0.0,
        signal_memory_ticks=1,
    )

    closes = list(np.linspace(200, 100, 80))
    df = pd.DataFrame({
        "open": closes,
        "high": [c * 1.005 for c in closes],
        "low": [c * 0.995 for c in closes],
        "close": closes,
        "volume": [1000] * len(closes),
    })
    candles = compute_indicators(df)

    sig_a = _sig("rsi_reversal", "BUY", 0.8)
    sig_b = _sig("ema_breakout", "BUY", 0.75)

    with patch("app.engine.orchestrator.get_settings", return_value=no_mem_settings):
        orch.signal_agent.generate = lambda sym, c, **kw: [sig_a]
        outcomes_1 = orch.run("TEST", candles)

        orch.signal_agent.generate = lambda sym, c, **kw: [sig_b]
        outcomes_2 = orch.run("TEST", candles)

    # Both ticks should fail — memory disabled, only 1 strategy per tick
    assert len(outcomes_1) == 0
    assert len(outcomes_2) == 0


def test_signal_memory_expires_old_signals() -> None:
    """Signals older than the memory window should be pruned."""
    from unittest.mock import patch

    import numpy as np
    import pandas as pd

    from app.engine.orchestrator import Orchestrator
    from app.models import Base
    from app.services.broker.paper_broker import PaperBroker
    from app.services.market_data import compute_indicators
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine("sqlite:///:memory:", future=True, connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    broker = PaperBroker(quote_fn=lambda s: 100.0)
    orch = Orchestrator(broker=broker, session_factory=factory)

    short_mem = Settings(
        mode="paper", min_strategy_agreement=2, min_signal_confidence=0.0,
        signal_memory_ticks=2,  # only 2 ticks
    )

    closes = list(np.linspace(200, 100, 80))
    df = pd.DataFrame({
        "open": closes,
        "high": [c * 1.005 for c in closes],
        "low": [c * 0.995 for c in closes],
        "close": closes,
        "volume": [1000] * len(closes),
    })
    candles = compute_indicators(df)

    sig_a = _sig("rsi_reversal", "BUY", 0.8)
    sig_b = _sig("ema_breakout", "BUY", 0.75)

    with patch("app.engine.orchestrator.get_settings", return_value=short_mem):
        # Tick 1: rsi fires
        orch.signal_agent.generate = lambda sym, c, **kw: [sig_a]
        orch.run("TEST", candles)

        # Tick 2: nothing fires (empty tick burns a slot)
        orch.signal_agent.generate = lambda sym, c, **kw: []
        orch.run("TEST", candles)

        # Tick 3: nothing fires (rsi signal from tick 1 is now expired)
        orch.signal_agent.generate = lambda sym, c, **kw: []
        orch.run("TEST", candles)

        # Tick 4: ema fires, but rsi is expired → only 1 → no conviction
        orch.signal_agent.generate = lambda sym, c, **kw: [sig_b]
        outcomes = orch.run("TEST", candles)

    assert len(outcomes) == 0