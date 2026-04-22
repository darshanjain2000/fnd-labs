"""Unit tests for :class:`app.services.signal_service.SignalService`."""
from __future__ import annotations

import pandas as pd

from app.services.signal_service import SignalService
from app.strategies.base import Signal, Strategy


class _FakeStrategy(Strategy):
    name = "fake"
    preferred_regimes = ("trend_up", "trend_down", "range", "high_vol")

    def __init__(self, signal: Signal | None = None, *, raises: Exception | None = None) -> None:
        self._signal = signal
        self._raises = raises

    def evaluate(self, symbol: str, candles: pd.DataFrame) -> Signal | None:
        if self._raises is not None:
            raise self._raises
        return self._signal


def _signal(side: str = "BUY", strategy: str = "fake") -> Signal:
    return Signal(
        symbol="X",
        strategy=strategy,
        side=side,
        entry=100.0,
        stop_loss=98.0,
        target=104.0,
        confidence=0.7,
    )


def test_generate_returns_signals_from_enabled_strategies(make_candles, make_settings) -> None:
    sig = _signal()
    svc = SignalService(strategies=[_FakeStrategy(sig)], settings=make_settings())
    out = svc.generate("X", make_candles())
    assert out == [sig]


def test_generate_swallows_strategy_exceptions(make_candles, make_settings) -> None:
    svc = SignalService(
        strategies=[_FakeStrategy(raises=RuntimeError("boom"))],
        settings=make_settings(),
    )
    assert svc.generate("X", make_candles()) == []


def test_generate_skips_strategies_that_dont_match_regime(make_candles, make_settings) -> None:
    class OnlyRange(_FakeStrategy):
        preferred_regimes = ("range",)

    svc = SignalService(
        strategies=[OnlyRange(_signal())],
        settings=make_settings(regime_filter_enabled=True),
    )
    # Default candles drift down with wide wicks → detected regime is "high_vol",
    # so a strategy restricted to "range" must be filtered out.
    assert svc.generate("X", make_candles()) == []


def test_generate_applies_htf_agreement_filter(make_candles, make_settings) -> None:
    svc = SignalService(
        strategies=[_FakeStrategy(_signal("BUY"))],
        settings=make_settings(require_htf_agreement=True),
    )
    htf = pd.DataFrame({"ema20": [10.0], "ema50": [20.0]})  # 20>50 inverted → BUY rejected
    assert svc.generate("X", make_candles(), htf_candles=htf) == []


def test_generate_passes_htf_when_emas_align(make_candles, make_settings) -> None:
    sig = _signal("BUY")
    svc = SignalService(
        strategies=[_FakeStrategy(sig)],
        settings=make_settings(require_htf_agreement=True),
    )
    htf = pd.DataFrame({"ema20": [30.0], "ema50": [20.0]})  # BUY aligned
    assert svc.generate("X", make_candles(), htf_candles=htf) == [sig]
