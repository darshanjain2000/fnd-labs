import numpy as np
import pandas as pd

from app.services.market_data import compute_indicators
from app.strategies.rsi_reversal import RSIReversal


def _candles(closes: list[float]) -> pd.DataFrame:
    n = len(closes)
    df = pd.DataFrame({
        "open": closes,
        "high": [c * 1.005 for c in closes],
        "low": [c * 0.995 for c in closes],
        "close": closes,
        "volume": [1000] * n,
    })
    return compute_indicators(df)


def test_rsi_reversal_fires_on_deep_oversold():
    # monotonic decline -> RSI very low
    closes = list(np.linspace(200, 100, 60))
    df = _candles(closes)
    sig = RSIReversal().evaluate("X", df)
    assert sig is not None
    assert sig.side == "BUY"
    assert sig.stop_loss < sig.entry
    assert sig.target > sig.entry


def test_rsi_reversal_fires_on_overbought():
    closes = list(np.linspace(100, 200, 60))
    df = _candles(closes)
    sig = RSIReversal().evaluate("X", df)
    assert sig is not None
    assert sig.side == "SELL"
    assert sig.stop_loss > sig.entry


def test_rsi_reversal_silent_in_range():
    closes = [100 + (i % 2) * 0.5 for i in range(60)]
    df = _candles(closes)
    assert RSIReversal().evaluate("X", df) is None
