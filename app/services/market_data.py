"""Market data service: OHLC fetch + indicator computation.

Supports pandas DataFrames provided by callers (tests, backtests) and exposes
indicator helpers. Uses pandas_ta when installed; falls back to pure numpy/pandas.

Indicators computed: rsi, ema20, ema50, vwap, atr14, macd, macd_signal, macd_hist,
bb_upper, bb_mid, bb_lower, bb_width, stoch_k, stoch_d, obv, adx,
supertrend, supertrend_dir.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

try:
    import pandas_ta as ta  # type: ignore
except ImportError:  # pragma: no cover
    ta = None


REQUIRED_COLS = {"open", "high", "low", "close", "volume"}


def _validate(df: pd.DataFrame) -> None:
    """Raise ValueError if required OHLCV columns are missing."""
    missing = REQUIRED_COLS - set(df.columns.str.lower())
    if missing:
        raise ValueError(f"candles missing columns: {missing}")


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy of *df* with all technical indicators appended.

    Indicators added: rsi, ema20, ema50, vwap, atr14, macd, macd_signal,
    macd_hist, bb_upper, bb_mid, bb_lower, bb_width, stoch_k, stoch_d,
    obv, adx, supertrend, supertrend_dir.

    Args:
        df: OHLCV DataFrame (column names are case-insensitive).

    Returns:
        Copy of *df* with indicator columns added.
    """
    _validate(df)
    out = df.copy()
    out.columns = [c.lower() for c in out.columns]

    if ta is None:  # graceful fallback when pandas_ta not installed
        _compute_fallback(out)
    else:
        _compute_pandas_ta(out)
    return out


# ---------------------------------------------------------------------------
# Pure pandas/numpy fallback (no pandas_ta dependency)
# ---------------------------------------------------------------------------


def _compute_fallback(out: pd.DataFrame) -> None:
    """Compute all indicators in-place using only numpy and pandas."""
    # RSI (14)
    delta = out["close"].diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss.replace(0, 1e-9)
    out["rsi"] = 100 - (100 / (1 + rs))

    # EMAs
    out["ema20"] = out["close"].ewm(span=20, adjust=False).mean()
    out["ema50"] = out["close"].ewm(span=50, adjust=False).mean()

    # VWAP (cumulative, resets per session if index is DatetimeIndex)
    tp = (out["high"] + out["low"] + out["close"]) / 3
    out["vwap"] = (tp * out["volume"]).cumsum() / out["volume"].cumsum()

    # ATR (14)
    tr = pd.concat(
        [
            (out["high"] - out["low"]).abs(),
            (out["high"] - out["close"].shift()).abs(),
            (out["low"] - out["close"].shift()).abs(),
        ],
        axis=1,
    ).max(axis=1)
    out["atr14"] = tr.rolling(14).mean()

    # MACD (12/26/9)
    ema12 = out["close"].ewm(span=12, adjust=False).mean()
    ema26 = out["close"].ewm(span=26, adjust=False).mean()
    out["macd"] = ema12 - ema26
    out["macd_signal"] = out["macd"].ewm(span=9, adjust=False).mean()
    out["macd_hist"] = out["macd"] - out["macd_signal"]

    # Bollinger Bands (20, 2σ)
    bb_mid = out["close"].rolling(20).mean()
    bb_std = out["close"].rolling(20).std()
    out["bb_upper"] = bb_mid + 2 * bb_std
    out["bb_mid"] = bb_mid
    out["bb_lower"] = bb_mid - 2 * bb_std
    out["bb_width"] = (out["bb_upper"] - out["bb_lower"]) / bb_mid.replace(0, 1e-9)

    # Stochastic %K/%D (14, 3)
    low14 = out["low"].rolling(14).min()
    high14 = out["high"].rolling(14).max()
    out["stoch_k"] = 100 * (out["close"] - low14) / (high14 - low14).replace(0, 1e-9)
    out["stoch_d"] = out["stoch_k"].rolling(3).mean()

    # OBV
    direction = (
        out["close"].diff().apply(lambda x: 1 if x > 0 else (-1 if x < 0 else 0))
    )
    out["obv"] = (direction * out["volume"]).cumsum()

    # ADX (14)
    out["adx"] = _adx_fallback(out, period=14)

    # Supertrend (10, 3.0)
    _supertrend_fallback(out, period=10, multiplier=3.0)


def _adx_fallback(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Compute ADX using Wilder smoothing (pure pandas).

    Args:
        df: DataFrame with high/low/close columns.
        period: Smoothing period (default 14).

    Returns:
        ADX Series aligned to df's index.
    """
    high, low, close = df["high"], df["low"], df["close"]
    tr = pd.concat(
        [
            (high - low).abs(),
            (high - close.shift()).abs(),
            (low - close.shift()).abs(),
        ],
        axis=1,
    ).max(axis=1)

    plus_dm = high.diff()
    minus_dm = -low.diff()
    plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
    minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0.0)

    alpha = 1.0 / period
    atr_s = tr.ewm(alpha=alpha, adjust=False).mean()
    plus_di = (
        100 * plus_dm.ewm(alpha=alpha, adjust=False).mean() / atr_s.replace(0, 1e-9)
    )
    minus_di = (
        100 * minus_dm.ewm(alpha=alpha, adjust=False).mean() / atr_s.replace(0, 1e-9)
    )
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, 1e-9)
    return dx.ewm(alpha=alpha, adjust=False).mean()


def _supertrend_fallback(
    df: pd.DataFrame, period: int = 10, multiplier: float = 3.0
) -> None:
    """Compute Supertrend and add *supertrend* / *supertrend_dir* columns in-place.

    Args:
        df: DataFrame with high/low/close columns (modified in-place).
        period: ATR lookback period.
        multiplier: ATR multiplier for band width.
    """
    high = df["high"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)
    close = df["close"].to_numpy(dtype=float)
    n = len(df)

    # True range
    prev_close = np.concatenate([[np.nan], close[:-1]])
    tr = np.maximum(
        high - low, np.maximum(np.abs(high - prev_close), np.abs(low - prev_close))
    )

    # ATR via rolling simple mean (sequential to match standard definition)
    atr = np.full(n, np.nan)
    for i in range(period - 1, n):
        atr[i] = np.nanmean(tr[max(0, i - period + 1) : i + 1])

    hl2 = (high + low) / 2.0
    basic_upper = hl2 + multiplier * atr
    basic_lower = hl2 - multiplier * atr

    final_upper = basic_upper.copy()
    final_lower = basic_lower.copy()
    supertrend = np.full(n, np.nan)
    direction = np.ones(n, dtype=float)  # 1.0 = bullish, -1.0 = bearish

    for i in range(period, n):
        pu, pl = final_upper[i - 1], final_lower[i - 1]
        final_upper[i] = (
            basic_upper[i] if (basic_upper[i] < pu or close[i - 1] > pu) else pu
        )
        final_lower[i] = (
            basic_lower[i] if (basic_lower[i] > pl or close[i - 1] < pl) else pl
        )

        prev_dir = direction[i - 1]
        if prev_dir == -1.0 and close[i] > final_upper[i]:
            direction[i] = 1.0
        elif prev_dir == 1.0 and close[i] < final_lower[i]:
            direction[i] = -1.0
        else:
            direction[i] = prev_dir

        supertrend[i] = final_lower[i] if direction[i] == 1.0 else final_upper[i]

    df["supertrend"] = supertrend
    df["supertrend_dir"] = direction


# ---------------------------------------------------------------------------
# pandas_ta-backed computation
# ---------------------------------------------------------------------------


def _compute_pandas_ta(out: pd.DataFrame) -> None:
    """Use pandas_ta for indicator computation (faster, more precise)."""
    out["rsi"] = ta.rsi(out["close"], length=14)
    out["ema20"] = ta.ema(out["close"], length=20)
    out["ema50"] = ta.ema(out["close"], length=50)
    out["vwap"] = ta.vwap(
        high=out["high"], low=out["low"], close=out["close"], volume=out["volume"]
    )
    out["atr14"] = ta.atr(
        high=out["high"], low=out["low"], close=out["close"], length=14
    )

    macd_df = ta.macd(out["close"], fast=12, slow=26, signal=9)
    if macd_df is not None and not macd_df.empty:
        out["macd"] = macd_df.iloc[:, 0]
        out["macd_signal"] = macd_df.iloc[:, 2]
        out["macd_hist"] = macd_df.iloc[:, 1]
    else:
        out["macd"] = out["macd_signal"] = out["macd_hist"] = float("nan")

    bb_df = ta.bbands(out["close"], length=20, std=2)
    if bb_df is not None and not bb_df.empty:
        out["bb_lower"] = bb_df.iloc[:, 0]
        out["bb_mid"] = bb_df.iloc[:, 1]
        out["bb_upper"] = bb_df.iloc[:, 2]
        out["bb_width"] = bb_df.iloc[:, 3]
    else:
        out["bb_upper"] = out["bb_mid"] = out["bb_lower"] = out["bb_width"] = float(
            "nan"
        )

    stoch_df = ta.stoch(out["high"], out["low"], out["close"], k=14, d=3)
    if stoch_df is not None and not stoch_df.empty:
        out["stoch_k"] = stoch_df.iloc[:, 0]
        out["stoch_d"] = stoch_df.iloc[:, 1]
    else:
        out["stoch_k"] = out["stoch_d"] = float("nan")

    obv = ta.obv(out["close"], out["volume"])
    out["obv"] = obv if obv is not None else float("nan")

    adx_df = ta.adx(out["high"], out["low"], out["close"], length=14)
    out["adx"] = (
        adx_df.iloc[:, 0] if (adx_df is not None and not adx_df.empty) else float("nan")
    )

    # Supertrend: use pure-numpy fallback for cross-version compatibility
    _supertrend_fallback(out, period=10, multiplier=3.0)


# ---------------------------------------------------------------------------
# Higher-timeframe resampling
# ---------------------------------------------------------------------------


def resample_to_htf(df: pd.DataFrame, target_interval: str = "15min") -> pd.DataFrame:
    """Resample OHLCV candles to a higher timeframe and compute indicators.

    Args:
        df: OHLCV DataFrame with a ``pd.DatetimeIndex``.
        target_interval: Pandas offset alias (e.g. ``"15min"``, ``"1h"``).

    Returns:
        Resampled DataFrame with all indicators at the target interval.

    Raises:
        ValueError: If *df* does not have a DatetimeIndex.
    """
    if not isinstance(df.index, pd.DatetimeIndex):
        raise ValueError("resample_to_htf requires a DatetimeIndex on df")
    work = df.copy()
    work.columns = [c.lower() for c in work.columns]
    agg_map = {
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    }
    resampled = work.resample(target_interval).agg(agg_map).dropna(subset=["close"])
    return compute_indicators(resampled)
