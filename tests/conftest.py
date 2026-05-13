"""Shared pytest fixtures for the fnd-labs test suite.

All fixtures here are factories (the fixture returns a callable) so each test
can override only the fields it cares about. Fixtures deliberately have
permissive defaults — the tests that depend on strict conditions (e.g. risk
gate thresholds) override those fields explicitly.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import Settings
from app.engine.risk_engine import RiskEngine
from app.models import Base
from app.services.broker.paper_broker import PaperBroker
from app.services.market_data import compute_indicators
from app.strategies.base import Signal


# ---------------------------------------------------------------------------
# Signal factory — unifies the two _sig() helpers previously duplicated
# across test_risk_engine.py and test_orchestrator_conviction.py.
# ---------------------------------------------------------------------------
@pytest.fixture
def make_signal() -> Callable[..., Signal]:
    """Return a factory that builds a ``Signal`` with test-friendly defaults.

    Any field can be overridden via keyword args. Defaults are chosen so the
    signal passes most risk gates (entry=100, stop=98 → 2 pt risk; target=104).

    Returns:
        Callable that builds and returns a ``Signal`` instance.
    """

    def _make(
        *,
        symbol: str = "X",
        strategy: str = "t",
        side: str = "BUY",
        entry: float = 100.0,
        stop_loss: float = 98.0,
        target: float = 104.0,
        confidence: float = 0.7,
        **extra: Any,
    ) -> Signal:
        return Signal(
            symbol=symbol,
            strategy=strategy,
            side=side,
            entry=entry,
            stop_loss=stop_loss,
            target=target,
            confidence=confidence,
            **extra,
        )

    return _make


# ---------------------------------------------------------------------------
# Settings factory — replaces _settings()/_permissive_settings() helpers.
# ---------------------------------------------------------------------------
@pytest.fixture
def make_settings() -> Callable[..., Settings]:
    """Return a factory that builds a ``Settings`` instance for tests.

    Defaults to ``mode='paper'`` with permissive gates
    (``min_strategy_agreement=1``, ``min_signal_confidence=0``) so a single
    signal flows through. Override any field via keyword args.

    Returns:
        Callable that builds and returns a ``Settings`` instance.
    """

    def _make(**overrides: Any) -> Settings:
        base: dict[str, Any] = dict(
            mode="paper",
            enabled_strategies="rsi_reversal,ema_breakout,vwap_pullback",
            min_strategy_agreement=1,
            min_signal_confidence=0.0,
            volume_filter_enabled=False,
            atr_filter_enabled=False,
            regime_filter_enabled=False,
            require_htf_agreement=False,
            rr_gate_enabled=False,
        )
        base.update(overrides)
        return Settings(**base)

    return _make


# ---------------------------------------------------------------------------
# RiskEngine factory — replaces _engine() in test_risk_engine.py.
# ---------------------------------------------------------------------------
@pytest.fixture
def make_risk_engine() -> Callable[..., RiskEngine]:
    """Return a factory that builds a ``RiskEngine`` with test-friendly defaults.

    Defaults: ``capital=100k``, ``risk/trade=1%``, ``daily_loss=2%``,
    ``max_open=3``, ``max_trades=5``, ``kill_switch=off``.

    Returns:
        Callable that builds and returns a ``RiskEngine`` instance.
    """

    def _make(**overrides: Any) -> RiskEngine:
        base: dict[str, Any] = dict(
            mode="paper",
            capital_inr=100_000.0,
            max_risk_per_trade_pct=1.0,
            max_daily_loss_pct=2.0,
            max_open_positions=3,
            max_trades_per_day=5,
            kill_switch=False,
            block_expiry_last_hours=2,
        )
        base.update(overrides)
        return RiskEngine(settings=Settings(**base))

    return _make


# ---------------------------------------------------------------------------
# In-memory DB session factory — replaces _make_db_factory() helpers.
# ---------------------------------------------------------------------------
@pytest.fixture
def db_factory() -> Callable[[], sessionmaker]:
    """Return a factory that creates a fresh in-memory SQLite ``sessionmaker``.

    Each call creates a new engine + schema, so tests stay isolated. Use
    ``factory = db_factory()`` to get a sessionmaker, then ``with factory() as
    session:`` as usual.

    Returns:
        Callable returning a configured ``sessionmaker``.
    """

    def _make() -> sessionmaker:
        engine = create_engine(
            "sqlite:///:memory:",
            future=True,
            connect_args={"check_same_thread": False},
        )
        Base.metadata.create_all(bind=engine)
        return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

    return _make


# ---------------------------------------------------------------------------
# Candle builders — replace _oversold_candles() helper.
# ---------------------------------------------------------------------------
@pytest.fixture
def make_candles() -> Callable[..., pd.DataFrame]:
    """Return a factory that builds synthetic OHLCV candles with indicators.

    The factory takes a list of close prices; open/high/low are derived from
    close by ±0.5%, volume is a flat 1000. Useful for deterministic
    strategy/orchestrator tests.

    Returns:
        Callable that builds an indicator-enriched DataFrame.
    """

    def _make(closes: list[float] | None = None) -> pd.DataFrame:
        # Default: 60 bars, monotonic decline 200 → 100 (drives RSI deep oversold)
        if closes is None:
            closes = list(np.linspace(200, 100, 60))
        df = pd.DataFrame(
            {
                "open": closes,
                "high": [c * 1.005 for c in closes],
                "low": [c * 0.995 for c in closes],
                "close": closes,
                "volume": [1000] * len(closes),
            }
        )
        return compute_indicators(df)

    return _make


# ---------------------------------------------------------------------------
# Paper broker — replaces the `PaperBroker(quote_fn=lambda s: 100.0)` pattern.
# ---------------------------------------------------------------------------
@pytest.fixture
def make_paper_broker() -> Callable[..., PaperBroker]:
    """Return a factory that builds a ``PaperBroker`` with a constant quote.

    Defaults to quoting every symbol at 100.0. Override via ``quote=...`` or
    supply a custom ``quote_fn``.

    Returns:
        Callable that builds and returns a ``PaperBroker`` instance.
    """

    def _make(
        *,
        quote: float = 100.0,
        quote_fn: Callable[[str], float] | None = None,
    ) -> PaperBroker:
        fn = quote_fn if quote_fn is not None else (lambda _s: quote)
        return PaperBroker(quote_fn=fn)

    return _make
