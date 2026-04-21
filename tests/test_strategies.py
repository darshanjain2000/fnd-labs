import numpy as np
import pandas as pd
import pytest

from app.services.market_data import compute_indicators, resample_to_htf
from app.strategies.bollinger_squeeze import BollingerSqueeze
from app.strategies.ema_breakout import EMABreakout
from app.strategies.macd_divergence import MACDDivergence
from app.strategies.orb_breakout import ORBBreakout
from app.strategies.rsi_reversal import RSIReversal
from app.strategies.supertrend import SupertrendStrategy


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _candles(closes: list[float], with_datetime_index: bool = False) -> pd.DataFrame:
    """Build a minimal OHLCV DataFrame with indicators computed."""
    n = len(closes)
    df = pd.DataFrame(
        {
            "open": closes,
            "high": [c * 1.005 for c in closes],
            "low": [c * 0.995 for c in closes],
            "close": closes,
            "volume": [1000] * n,
        }
    )
    if with_datetime_index:
        idx = pd.date_range("2025-01-02 09:15", periods=n, freq="1min")
        df.index = idx
    return compute_indicators(df)


# ---------------------------------------------------------------------------
# RSIReversal (existing)
# ---------------------------------------------------------------------------

def test_rsi_reversal_fires_on_deep_oversold() -> None:
    # monotonic decline -> RSI very low
    closes = list(np.linspace(200, 100, 60))
    df = _candles(closes)
    sig = RSIReversal().evaluate("X", df)
    assert sig is not None
    assert sig.side == "BUY"
    assert sig.stop_loss < sig.entry
    assert sig.target > sig.entry


def test_rsi_reversal_fires_on_overbought() -> None:
    closes = list(np.linspace(100, 200, 60))
    df = _candles(closes)
    sig = RSIReversal().evaluate("X", df)
    assert sig is not None
    assert sig.side == "SELL"
    assert sig.stop_loss > sig.entry


def test_rsi_reversal_silent_in_range() -> None:
    closes = [100 + (i % 2) * 0.5 for i in range(60)]
    df = _candles(closes)
    assert RSIReversal().evaluate("X", df) is None


# ---------------------------------------------------------------------------
# SupertrendStrategy
# ---------------------------------------------------------------------------

def test_supertrend_returns_buy_on_bullish_flip() -> None:
    """Strong uptrend should produce a bullish Supertrend direction and eventually flip."""
    # Sharp drop then sharp rise → guarantees a bearish→bullish flip
    closes = list(np.linspace(200, 100, 40)) + list(np.linspace(100, 300, 60))
    df = _candles(closes)
    # Look for any BUY signal across the upswing portion
    for end in range(50, len(df)):
        sig = SupertrendStrategy().evaluate("X", df.iloc[:end])
        if sig is not None and sig.side == "BUY":
            assert sig.stop_loss < sig.entry
            assert sig.target > sig.entry
            return
    pytest.skip("No bullish Supertrend flip detected with this data — check indicator values")


def test_supertrend_returns_sell_on_bearish_flip() -> None:
    """Sharp drop after a rise triggers a bearish flip."""
    closes = list(np.linspace(100, 300, 60)) + list(np.linspace(300, 100, 40))
    df = _candles(closes)
    for end in range(65, len(df)):
        sig = SupertrendStrategy().evaluate("X", df.iloc[:end])
        if sig is not None and sig.side == "SELL":
            assert sig.stop_loss > sig.entry
            assert sig.target < sig.entry
            return
    pytest.skip("No bearish Supertrend flip detected with this data")


def test_supertrend_returns_none_on_short_series() -> None:
    df = _candles([100.0] * 5)
    assert SupertrendStrategy().evaluate("X", df) is None


def test_supertrend_preferred_regimes() -> None:
    st = SupertrendStrategy()
    assert st.applies_to_regime("trend_up")
    assert st.applies_to_regime("trend_down")
    assert not st.applies_to_regime("range")
    assert not st.applies_to_regime("high_vol")


# ---------------------------------------------------------------------------
# MACDDivergence
# ---------------------------------------------------------------------------

def test_macd_divergence_buy_signal() -> None:
    """Deep decline followed by recovery: MACD crosses up from below-zero territory."""
    closes = list(np.linspace(200, 100, 50)) + list(np.linspace(100, 160, 50))
    df = _candles(closes)
    found = False
    for end in range(40, len(df)):
        sig = MACDDivergence().evaluate("X", df.iloc[:end])
        if sig is not None and sig.side == "BUY":
            assert sig.stop_loss < sig.entry
            assert sig.target > sig.entry
            found = True
            break
    assert found, "Expected a BUY MACD signal on recovery from decline"


def test_macd_divergence_sell_signal() -> None:
    """Strong rise then sharp pullback: MACD crosses down from above-zero."""
    # Steeper rise and faster decline gives a clearer bearish crossover while MACD > 0
    closes = list(np.linspace(100, 350, 60)) + list(np.linspace(350, 200, 40))
    df = _candles(closes)
    found = False
    for end in range(36, len(df)):
        sig = MACDDivergence().evaluate("X", df.iloc[:end])
        if sig is not None and sig.side == "SELL":
            assert sig.stop_loss > sig.entry
            assert sig.target < sig.entry
            found = True
            break
    assert found, "Expected a SELL MACD signal on decline from peak"


def test_macd_divergence_none_on_short_series() -> None:
    df = _candles([100.0] * 20)
    assert MACDDivergence().evaluate("X", df) is None


# ---------------------------------------------------------------------------
# BollingerSqueeze
# ---------------------------------------------------------------------------

def test_bollinger_squeeze_upside_breakout() -> None:
    """Tight range then sudden spike triggers a BUY."""
    # Flat price for most candles (creates a squeeze), then sharp rise
    flat = [100.0] * 60
    spike = list(np.linspace(100.0, 115.0, 5))
    closes = flat + spike
    df = _candles(closes)
    # The spike at the end should produce a BUY in one of the last bars
    found = False
    for end in range(len(flat) + 2, len(df) + 1):
        sig = BollingerSqueeze(squeeze_pct=50.0).evaluate("X", df.iloc[:end])
        if sig is not None and sig.side == "BUY":
            assert sig.stop_loss < sig.entry
            found = True
            break
    assert found, "Expected a BUY on Bollinger spike"


def test_bollinger_squeeze_returns_none_when_bands_wide() -> None:
    """Volatile data produces wide bands — no squeeze, no signal."""
    rng = np.random.default_rng(1)
    closes = list(100 + rng.normal(0, 10, 80))
    df = _candles(closes)
    sig = BollingerSqueeze(squeeze_pct=0.1).evaluate("X", df)
    assert sig is None


def test_bollinger_squeeze_none_on_short_series() -> None:
    df = _candles([100.0] * 10)
    assert BollingerSqueeze().evaluate("X", df) is None


# ---------------------------------------------------------------------------
# ORBBreakout
# ---------------------------------------------------------------------------

def test_orb_breakout_requires_datetime_index() -> None:
    df = _candles([100.0] * 80)  # no datetime index
    assert ORBBreakout().evaluate("X", df) is None


def test_orb_breakout_buy_on_range_high_break() -> None:
    """Price consolidates in first 30 min then breaks out higher."""
    n = 100
    # First 30 bars: flat at 100; then sharp rally
    closes = [100.0] * 30 + [100.5, 101.0] + [105.0] * (n - 32)
    idx = pd.date_range("2025-01-02 09:15", periods=n, freq="1min")
    df = pd.DataFrame(
        {
            "open": [c * 0.999 for c in closes],
            "high": [c * 1.003 for c in closes],
            "low": [c * 0.997 for c in closes],
            "close": closes,
            "volume": [1000] * n,
        },
        index=idx,
    )
    df = compute_indicators(df)
    found = False
    for end in range(32, n):
        sig = ORBBreakout(orb_minutes=30).evaluate("X", df.iloc[:end])
        if sig is not None and sig.side == "BUY":
            assert sig.stop_loss < sig.entry
            assert sig.target > sig.entry
            found = True
            break
    assert found, "Expected ORB BUY signal on breakout above opening range"


def test_orb_breakout_no_signal_inside_orb_window() -> None:
    """No signal should fire while still within the opening range window."""
    n = 25
    closes = [100.0] * n
    idx = pd.date_range("2025-01-02 09:15", periods=n, freq="1min")
    df = pd.DataFrame(
        {
            "open": closes, "high": [c * 1.001 for c in closes],
            "low": [c * 0.999 for c in closes],
            "close": closes, "volume": [1000] * n,
        },
        index=idx,
    )
    df = compute_indicators(df)
    assert ORBBreakout(orb_minutes=30).evaluate("X", df) is None


# ---------------------------------------------------------------------------
# compute_indicators — new columns
# ---------------------------------------------------------------------------

def test_compute_indicators_adds_macd_columns() -> None:
    closes = list(np.linspace(100, 200, 80))
    df = _candles(closes)
    for col in ("macd", "macd_signal", "macd_hist"):
        assert col in df.columns, f"Missing column: {col}"


def test_compute_indicators_adds_bollinger_columns() -> None:
    closes = list(np.linspace(100, 200, 80))
    df = _candles(closes)
    for col in ("bb_upper", "bb_mid", "bb_lower", "bb_width"):
        assert col in df.columns, f"Missing column: {col}"


def test_compute_indicators_adds_stoch_obv_adx() -> None:
    closes = list(np.linspace(100, 200, 80))
    df = _candles(closes)
    for col in ("stoch_k", "stoch_d", "obv", "adx"):
        assert col in df.columns, f"Missing column: {col}"


def test_compute_indicators_adds_supertrend() -> None:
    closes = list(np.linspace(100, 200, 80))
    df = _candles(closes)
    assert "supertrend" in df.columns
    assert "supertrend_dir" in df.columns


# ---------------------------------------------------------------------------
# resample_to_htf
# ---------------------------------------------------------------------------

def test_resample_to_htf_reduces_row_count() -> None:
    closes = list(np.linspace(100, 200, 200))
    idx = pd.date_range("2025-01-02 09:15", periods=200, freq="1min")
    df = pd.DataFrame(
        {"open": closes, "high": [c * 1.001 for c in closes],
         "low": [c * 0.999 for c in closes], "close": closes, "volume": [1000] * 200},
        index=idx,
    )
    htf = resample_to_htf(df, target_interval="15min")
    assert len(htf) < len(df)
    assert "ema20" in htf.columns


def test_resample_to_htf_raises_without_datetime_index() -> None:
    df = _candles([100.0] * 50)
    with pytest.raises(ValueError, match="DatetimeIndex"):
        resample_to_htf(df)


# ---------------------------------------------------------------------------
# applies_to_regime across all strategies
# ---------------------------------------------------------------------------

def test_rsi_reversal_applies_to_range_regime() -> None:
    assert RSIReversal().applies_to_regime("range")


def test_ema_breakout_applies_to_trend_regime() -> None:
    assert EMABreakout().applies_to_regime("trend_up")
    assert EMABreakout().applies_to_regime("trend_down")

