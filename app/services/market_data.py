"""Market data service: OHLC fetch + indicator computation.

In Phase 1 the Kite historical path will be wired up. For now this module
supports pandas DataFrames provided by callers (tests, backtests) and exposes
indicator helpers.
"""
from __future__ import annotations

import pandas as pd

try:
    import pandas_ta as ta  # type: ignore
except ImportError:  # pragma: no cover
    ta = None


REQUIRED_COLS = {"open", "high", "low", "close", "volume"}


def _validate(df: pd.DataFrame) -> None:
    missing = REQUIRED_COLS - set(df.columns.str.lower())
    if missing:
        raise ValueError(f"candles missing columns: {missing}")


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy of df with rsi, ema20, ema50, vwap, atr14 columns appended."""
    _validate(df)
    out = df.copy()
    out.columns = [c.lower() for c in out.columns]

    if ta is None:  # graceful fallback when pandas_ta not installed in dev
        delta = out["close"].diff()
        gain = delta.clip(lower=0).rolling(14).mean()
        loss = (-delta.clip(upper=0)).rolling(14).mean()
        rs = gain / loss.replace(0, 1e-9)
        out["rsi"] = 100 - (100 / (1 + rs))
        out["ema20"] = out["close"].ewm(span=20, adjust=False).mean()
        out["ema50"] = out["close"].ewm(span=50, adjust=False).mean()
        tp = (out["high"] + out["low"] + out["close"]) / 3
        out["vwap"] = (tp * out["volume"]).cumsum() / out["volume"].cumsum()
        tr = pd.concat(
            [
                (out["high"] - out["low"]).abs(),
                (out["high"] - out["close"].shift()).abs(),
                (out["low"] - out["close"].shift()).abs(),
            ],
            axis=1,
        ).max(axis=1)
        out["atr14"] = tr.rolling(14).mean()
        return out

    out["rsi"] = ta.rsi(out["close"], length=14)
    out["ema20"] = ta.ema(out["close"], length=20)
    out["ema50"] = ta.ema(out["close"], length=50)
    out["vwap"] = ta.vwap(high=out["high"], low=out["low"], close=out["close"], volume=out["volume"])
    out["atr14"] = ta.atr(high=out["high"], low=out["low"], close=out["close"], length=14)
    return out
