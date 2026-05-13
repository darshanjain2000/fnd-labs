"""Unit tests for :class:`app.services.signal_service.SignalService`."""

from __future__ import annotations

import pandas as pd

from app.services.signal_service import SignalService
from app.strategies.base import Signal, Strategy


class _FakeStrategy(Strategy):
    name = "fake"
    preferred_regimes = ("trend_up", "trend_down", "range", "high_vol")

    def __init__(
        self, signal: Signal | None = None, *, raises: Exception | None = None
    ) -> None:
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


def test_generate_returns_signals_from_enabled_strategies(
    make_candles, make_settings
) -> None:
    sig = _signal()
    svc = SignalService(
        strategies=[_FakeStrategy(sig)],
        settings=make_settings(volume_filter_enabled=False, atr_filter_enabled=False),
    )
    out = svc.generate("X", make_candles())
    assert out == [sig]


def test_generate_swallows_strategy_exceptions(make_candles, make_settings) -> None:
    svc = SignalService(
        strategies=[_FakeStrategy(raises=RuntimeError("boom"))],
        settings=make_settings(),
    )
    assert svc.generate("X", make_candles()) == []


def test_generate_skips_strategies_that_dont_match_regime(
    make_candles, make_settings
) -> None:
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
    htf = pd.DataFrame(
        {"ema20": [10.0], "ema50": [20.0]}
    )  # 20>50 inverted → BUY rejected
    assert svc.generate("X", make_candles(), htf_candles=htf) == []


def test_generate_passes_htf_when_emas_align(make_candles, make_settings) -> None:
    sig = _signal("BUY")
    svc = SignalService(
        strategies=[_FakeStrategy(sig)],
        settings=make_settings(
            require_htf_agreement=True,
            volume_filter_enabled=False,
            atr_filter_enabled=False,
        ),
    )
    htf = pd.DataFrame({"ema20": [30.0], "ema50": [20.0]})  # BUY aligned
    assert svc.generate("X", make_candles(), htf_candles=htf) == [sig]


# ---------------------------------------------------------------------------
# enabled_strategies filtering
# ---------------------------------------------------------------------------


def test_filter_enabled_returns_only_listed_strategies(make_settings) -> None:
    """When enabled_strategies is set, only matching strategies are returned."""
    settings = make_settings(enabled_strategies="fake")

    class _AnotherFake(Strategy):
        name = "other"
        preferred_regimes = ("trend_up", "trend_down", "range", "high_vol")

        def evaluate(self, symbol: str, candles: pd.DataFrame) -> Signal | None:
            return None

    svc = SignalService(settings=settings)
    filtered = svc._filter_enabled([_FakeStrategy(), _AnotherFake()])
    assert len(filtered) == 1
    assert filtered[0].name == "fake"


def test_filter_enabled_returns_all_when_empty(make_settings) -> None:
    """When enabled_strategies is empty, all strategies pass through."""
    settings = make_settings(enabled_strategies="")
    svc = SignalService(settings=settings)
    strats = [_FakeStrategy(), _FakeStrategy()]
    assert svc._filter_enabled(strats) == strats


def test_generate_rejects_signal_when_volume_too_low(make_settings) -> None:
    """Volume gate filters signals when current bar volume is below 1.5x the 20-bar avg."""
    import numpy as np

    from app.services.market_data import compute_indicators

    sig = _signal()
    svc = SignalService(
        strategies=[_FakeStrategy(sig)],
        settings=make_settings(volume_filter_enabled=True, min_volume_multiple=1.5),
    )
    closes = list(np.linspace(200, 100, 60))
    # Flat volume: current bar volume equals the average (ratio = 1.0 < 1.5)
    df = pd.DataFrame(
        {
            "open": closes,
            "high": [c * 1.005 for c in closes],
            "low": [c * 0.995 for c in closes],
            "close": closes,
            "volume": [1000.0] * 60,
        }
    )
    df = compute_indicators(df)
    assert svc.generate("X", df) == []


def test_generate_passes_signal_when_volume_high(make_settings) -> None:
    """Volume gate allows signals when current bar volume exceeds 1.5x the 20-bar avg."""
    import numpy as np

    from app.services.market_data import compute_indicators

    sig = _signal()
    svc = SignalService(
        strategies=[_FakeStrategy(sig)],
        settings=make_settings(volume_filter_enabled=True, min_volume_multiple=1.5),
    )
    closes = list(np.linspace(200, 100, 60))
    volumes = [1000.0] * 59 + [2000.0]  # last bar 2x avg => passes 1.5x gate
    df = pd.DataFrame(
        {
            "open": closes,
            "high": [c * 1.005 for c in closes],
            "low": [c * 0.995 for c in closes],
            "close": closes,
            "volume": volumes,
        }
    )
    df = compute_indicators(df)
    assert svc.generate("X", df) == [sig]


def test_generate_rejects_signal_when_atr_too_low(make_settings) -> None:
    """ATR gate filters signals when ATR is below min_atr_pct of price."""
    from app.services.market_data import compute_indicators

    sig = _signal()
    svc = SignalService(
        strategies=[_FakeStrategy(sig)],
        settings=make_settings(atr_filter_enabled=True, min_atr_pct=5.0),
    )
    # Flat prices => ATR ~= 0 => always below 5% threshold
    closes = [100.0] * 60
    df = pd.DataFrame(
        {
            "open": closes,
            "high": closes,
            "low": closes,
            "close": closes,
            "volume": [1000.0] * 60,
        }
    )
    df = compute_indicators(df)
    assert svc.generate("X", df) == []
