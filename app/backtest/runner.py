"""Vectorised event-driven backtester for single strategies.

Usage (CLI)::

    python -m app.backtest.runner \\
        --symbol NIFTY \\
        --strategy ema_breakout \\
        --from 2025-01-01 \\
        --to   2025-04-01 \\
        --capital 25000 \\
        --risk-pct 1.0

Or from Python::

    from app.backtest.runner import BacktestResult, run_backtest
    result = run_backtest(df, strategies=[EMABreakout()], capital=25_000)
    print(result.summary())
"""
from __future__ import annotations

import argparse
import math
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import numpy as np
import pandas as pd

from app.core.logging import get_logger
from app.engine.risk_engine import position_size
from app.services.market_data import compute_indicators
from app.strategies.base import Strategy

log = get_logger(__name__)

# Warm-up candles required before the first evaluation
_WARMUP_BARS = 60


@dataclass
class TradeRecord:
    """Single simulated trade outcome."""

    symbol: str
    strategy: str
    side: str
    entry: float
    exit: float
    stop_loss: float
    target: float | None
    qty: int
    pnl: float
    bars_held: int
    exit_reason: str  # "target" | "stop" | "trailing" | "eod"


@dataclass
class BacktestResult:
    """Aggregated backtest metrics for one strategy / symbol run.

    Attributes:
        symbol: Symbol backtested.
        strategy: Strategy name.
        trades: List of individual trade records.
        capital_start: Starting capital (INR).
        capital_end: Final equity (INR).
        total_pnl: Sum of all trade PnLs.
        win_rate: Fraction of winning trades.
        sharpe: Annualised Sharpe ratio (daily returns, rf=0).
        sortino: Annualised Sortino ratio (daily downside deviation, rf=0).
        max_drawdown_pct: Maximum peak-to-trough drawdown as a percentage.
        from_date: First date in the data.
        to_date: Last date in the data.
    """

    symbol: str
    strategy: str
    trades: list[TradeRecord] = field(default_factory=list)
    capital_start: float = 0.0
    capital_end: float = 0.0
    total_pnl: float = 0.0
    win_rate: float = 0.0
    sharpe: float = 0.0
    sortino: float = 0.0
    max_drawdown_pct: float = 0.0
    from_date: date | None = None
    to_date: date | None = None

    def summary(self) -> dict[str, Any]:
        """Return a plain-dict summary suitable for logging or JSON output."""
        return {
            "symbol": self.symbol,
            "strategy": self.strategy,
            "from": str(self.from_date),
            "to": str(self.to_date),
            "trades": len(self.trades),
            "win_rate": round(self.win_rate, 4),
            "total_pnl": round(self.total_pnl, 2),
            "capital_end": round(self.capital_end, 2),
            "sharpe": round(self.sharpe, 4),
            "sortino": round(self.sortino, 4),
            "max_drawdown_pct": round(self.max_drawdown_pct, 4),
        }


def _compute_metrics(
    trades: list[TradeRecord],
    capital: float,
    df: pd.DataFrame,
) -> tuple[float, float, float, float]:
    """Compute win_rate, sharpe, sortino, max_drawdown from trade records.

    Args:
        trades: List of completed trade records.
        capital: Starting capital.
        df: OHLCV DataFrame (used for date range to normalise returns).

    Returns:
        Tuple of (win_rate, sharpe, sortino, max_drawdown_pct).
    """
    if not trades:
        return 0.0, 0.0, 0.0, 0.0

    pnls = [t.pnl for t in trades]
    wins = sum(1 for p in pnls if p > 0)
    win_rate = wins / len(pnls)

    # Build daily equity curve
    cumulative = np.cumsum(pnls)
    equity = capital + cumulative

    # Daily return approximation: spread PnL evenly (good enough for Sharpe estimation)
    daily_returns = np.diff(np.concatenate([[capital], equity])) / np.maximum(
        np.concatenate([[capital], equity[:-1]]), 1e-9
    )

    mean_r = float(np.mean(daily_returns))
    std_r = float(np.std(daily_returns, ddof=1)) if len(daily_returns) > 1 else 1e-9
    sharpe = mean_r / std_r * math.sqrt(252) if std_r > 0 else 0.0

    downside = daily_returns[daily_returns < 0]
    std_down = float(np.std(downside, ddof=1)) if len(downside) > 1 else 1e-9
    sortino = mean_r / std_down * math.sqrt(252) if std_down > 0 else 0.0

    # Maximum drawdown
    peak = np.maximum.accumulate(equity)
    drawdowns = (equity - peak) / np.maximum(peak, 1e-9)
    max_drawdown_pct = float(abs(drawdowns.min())) if len(drawdowns) > 0 else 0.0

    return win_rate, sharpe, sortino, max_drawdown_pct


def run_backtest(
    df: pd.DataFrame,
    strategies: list[Strategy],
    symbol: str = "BACKTEST",
    capital: float = 25_000.0,
    lot_size: int = 1,
    risk_pct: float = 1.0,
    slippage_bps: float = 4.0,
    brokerage_per_rt: float = 40.0,
    trailing_atr_mult: float = 0.0,
) -> list[BacktestResult]:
    """Run an event-driven backtest for each strategy independently.

    For every bar (after the warm-up window) the strategy is evaluated on
    candles ``[:i+1]``. If there is no open position and a signal fires, a
    virtual trade is opened. Each subsequent bar checks whether the stop-loss
    or target has been hit (using the high/low of the bar); otherwise the
    trade is held until end-of-data.

    Args:
        df: OHLCV DataFrame with pre-computed indicators (or raw OHLCV — indicators
            are computed if not already present). Must have ``open/high/low/close/volume``.
        strategies: List of Strategy instances to backtest.
        symbol: Symbol name used in trade records.
        capital: Starting capital in INR.
        lot_size: F&O lot size (position must be a multiple of this).
        risk_pct: Maximum per-trade risk as a percentage of capital.
        slippage_bps: One-way slippage in basis points (applied to entry/exit price).
        brokerage_per_rt: Round-trip brokerage cost in INR.
        trailing_atr_mult: If > 0, use ATR-based trailing stop (e.g. 1.5 = 1.5x ATR).
            Stop ratchets in the direction of profit each bar. Set 0 to disable.

    Returns:
        One BacktestResult per strategy.
    """
    # Ensure indicators are present
    if "rsi" not in df.columns:
        df = compute_indicators(df)

    slip_factor = slippage_bps / 10_000.0

    results: list[BacktestResult] = []

    for strat in strategies:
        trades: list[TradeRecord] = []
        open_trade: dict | None = None
        current_capital = capital

        for i in range(_WARMUP_BARS, len(df)):
            bar = df.iloc[i]
            bar_high = float(bar["high"])
            bar_low = float(bar["low"])
            bar_close = float(bar["close"])

            # -- Check open trade for exit --
            if open_trade is not None:
                exit_price: float | None = None
                exit_reason = "eod"

                if open_trade["side"] == "BUY":
                    if bar_low <= open_trade["stop"]:
                        exit_price = open_trade["stop"]
                        exit_reason = "trailing" if open_trade.get("trailed") else "stop"
                    elif open_trade["target"] and bar_high >= open_trade["target"]:
                        exit_price = open_trade["target"]
                        exit_reason = "target"
                else:  # SELL
                    if bar_high >= open_trade["stop"]:
                        exit_price = open_trade["stop"]
                        exit_reason = "trailing" if open_trade.get("trailed") else "stop"
                    elif open_trade["target"] and bar_low <= open_trade["target"]:
                        exit_price = open_trade["target"]
                        exit_reason = "target"

                # -- ATR trailing stop update --
                if exit_price is None and trailing_atr_mult > 0 and "atr14" in df.columns:
                    atr_val = float(bar.get("atr14", 0.0))
                    if atr_val > 0:
                        trail_dist = atr_val * trailing_atr_mult
                        if open_trade["side"] == "BUY":
                            new_stop = bar_close - trail_dist
                            if new_stop > open_trade["stop"]:
                                open_trade["stop"] = round(new_stop, 2)
                                open_trade["trailed"] = True
                        else:
                            new_stop = bar_close + trail_dist
                            if new_stop < open_trade["stop"]:
                                open_trade["stop"] = round(new_stop, 2)
                                open_trade["trailed"] = True

                if exit_price is not None:
                    qty = open_trade["qty"]
                    raw_pnl = (
                        (exit_price - open_trade["entry"]) * qty
                        if open_trade["side"] == "BUY"
                        else (open_trade["entry"] - exit_price) * qty
                    )
                    slippage_cost = exit_price * slip_factor * qty
                    net_pnl = raw_pnl - slippage_cost - brokerage_per_rt / 2
                    current_capital += net_pnl
                    trades.append(
                        TradeRecord(
                            symbol=symbol,
                            strategy=strat.name,
                            side=open_trade["side"],
                            entry=open_trade["entry"],
                            exit=exit_price,
                            stop_loss=open_trade["stop"],
                            target=open_trade["target"],
                            qty=qty,
                            pnl=round(net_pnl, 2),
                            bars_held=i - open_trade["bar"],
                            exit_reason=exit_reason,
                        )
                    )
                    open_trade = None

            # -- Try to enter if no open trade --
            if open_trade is None:
                window = df.iloc[: i + 1]
                try:
                    sig = strat.evaluate(symbol, window)
                except Exception:  # strategy must not raise in backtest either
                    continue
                if sig is not None:
                    entry = float(bar["close"])
                    entry_with_slip = (
                        entry * (1 + slip_factor) if sig.side == "BUY" else entry * (1 - slip_factor)
                    )
                    qty = position_size(current_capital, risk_pct, entry_with_slip, sig.stop_loss, lot_size)
                    if qty >= 1:
                        open_trade = {
                            "side": sig.side,
                            "entry": round(entry_with_slip, 2),
                            "stop": sig.stop_loss,
                            "target": sig.target,
                            "qty": qty,
                            "bar": i,
                        }

        # Close any still-open position at EOD
        if open_trade is not None:
            last_close = float(df.iloc[-1]["close"])
            qty = open_trade["qty"]
            raw_pnl = (
                (last_close - open_trade["entry"]) * qty
                if open_trade["side"] == "BUY"
                else (open_trade["entry"] - last_close) * qty
            )
            slippage_cost = last_close * slip_factor * qty
            net_pnl = raw_pnl - slippage_cost - brokerage_per_rt / 2
            current_capital += net_pnl
            trades.append(
                TradeRecord(
                    symbol=symbol,
                    strategy=strat.name,
                    side=open_trade["side"],
                    entry=open_trade["entry"],
                    exit=last_close,
                    stop_loss=open_trade["stop"],
                    target=open_trade["target"],
                    qty=qty,
                    pnl=round(net_pnl, 2),
                    bars_held=len(df) - 1 - open_trade["bar"],
                    exit_reason="eod",
                )
            )

        win_rate, sharpe, sortino, max_dd = _compute_metrics(trades, capital, df)
        total_pnl = sum(t.pnl for t in trades)
        from_date = df.index[0].date() if isinstance(df.index, pd.DatetimeIndex) else None
        to_date = df.index[-1].date() if isinstance(df.index, pd.DatetimeIndex) else None

        result = BacktestResult(
            symbol=symbol,
            strategy=strat.name,
            trades=trades,
            capital_start=capital,
            capital_end=round(capital + total_pnl, 2),
            total_pnl=round(total_pnl, 2),
            win_rate=win_rate,
            sharpe=sharpe,
            sortino=sortino,
            max_drawdown_pct=max_dd,
            from_date=from_date,
            to_date=to_date,
        )
        log.info(
            "backtest_done",
            strategy=strat.name,
            symbol=symbol,
            trades=len(trades),
            pnl=total_pnl,
            sharpe=sharpe,
            win_rate=win_rate,
            from_date=str(from_date),
            to_date=str(to_date),
        )
        results.append(result)

    return results


def walk_forward(
    df: pd.DataFrame,
    strategies: list[Strategy],
    symbol: str = "BACKTEST",
    train_bars: int = 500,
    test_bars: int = 100,
    capital: float = 25_000.0,
    lot_size: int = 1,
    risk_pct: float = 1.0,
    trailing_atr_mult: float = 0.0,
) -> list[BacktestResult]:
    """Walk-forward validation: slide a train/test window across the data.

    The function splits *df* into successive windows of ``train_bars + test_bars``
    candles, advances by ``test_bars`` each step, and accumulates OOS results.

    Args:
        df: Full OHLCV DataFrame with indicators.
        strategies: Strategy instances to test.
        symbol: Symbol name.
        train_bars: Number of bars in the training window (unused by strategies
            that have no training phase — included for future ML strategies).
        test_bars: Number of bars in each OOS test window.
        capital: Starting capital per window.
        lot_size: F&O lot size.
        risk_pct: Per-trade risk percentage.
        trailing_atr_mult: ATR trailing stop multiplier (0 = disabled).

    Returns:
        One BacktestResult per strategy, aggregated across all OOS windows.
    """
    step = test_bars
    n = len(df)
    start = train_bars

    # Accumulate trades per strategy name
    all_trades: dict[str, list[TradeRecord]] = {s.name: [] for s in strategies}

    window_start = start
    while window_start + test_bars <= n:
        # Prepend warm-up bars from the training window so indicators are valid
        warmup_start = max(0, window_start - _WARMUP_BARS)
        eval_df = df.iloc[warmup_start: window_start + test_bars]
        window_results = run_backtest(
            eval_df, strategies, symbol=symbol,
            capital=capital, lot_size=lot_size, risk_pct=risk_pct,
            trailing_atr_mult=trailing_atr_mult,
        )
        for r in window_results:
            all_trades[r.strategy].extend(r.trades)
        window_start += step

    # Build aggregated results
    aggregated: list[BacktestResult] = []
    for strat in strategies:
        trades = all_trades[strat.name]
        total_pnl = sum(t.pnl for t in trades)
        win_rate, sharpe, sortino, max_dd = _compute_metrics(trades, capital, df)
        aggregated.append(
            BacktestResult(
                symbol=symbol,
                strategy=strat.name,
                trades=trades,
                capital_start=capital,
                capital_end=round(capital + total_pnl, 2),
                total_pnl=round(total_pnl, 2),
                win_rate=win_rate,
                sharpe=sharpe,
                sortino=sortino,
                max_drawdown_pct=max_dd,
                from_date=df.index[start].date() if isinstance(df.index, pd.DatetimeIndex) else None,
                to_date=df.index[-1].date() if isinstance(df.index, pd.DatetimeIndex) else None,
            )
        )
    return aggregated


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _build_sample_df(n: int = 800) -> pd.DataFrame:
    """Build a synthetic OHLCV DataFrame for smoke-testing the CLI."""
    rng = np.random.default_rng(42)
    closes = 20_000 + np.cumsum(rng.normal(0, 50, n))
    idx = pd.date_range("2025-04-02 09:15", periods=n, freq="1min")
    df = pd.DataFrame(
        {
            "open": closes * (1 - rng.uniform(0, 0.001, n)),
            "high": closes * (1 + rng.uniform(0, 0.002, n)),
            "low": closes * (1 - rng.uniform(0, 0.002, n)),
            "close": closes,
            "volume": rng.integers(1000, 50000, n),
        },
        index=idx,
    )
    return compute_indicators(df)


def _fetch_real_data(
    symbol: str,
    exchange: str,
    interval: str,
    from_date: str,
    to_date: str,
) -> pd.DataFrame:
    """Fetch real historical candles from Angel One SmartAPI.

    Args:
        symbol: NSE symbol (e.g. "NIFTY").
        exchange: Exchange segment (e.g. "NSE", "NFO").
        interval: Candle interval (e.g. "5m", "1d").
        from_date: Start date as YYYY-MM-DD string.
        to_date: End date as YYYY-MM-DD string.

    Returns:
        OHLCV DataFrame with DatetimeIndex and computed indicators.
    """
    from datetime import datetime as dt

    from app.services.angel_session import get_angel_session

    session = get_angel_session()
    from_dt = dt.strptime(from_date, "%Y-%m-%d").replace(hour=9, minute=15)
    to_dt = dt.strptime(to_date, "%Y-%m-%d").replace(hour=15, minute=30)

    log.info(
        "backtest_fetching_data",
        symbol=symbol,
        exchange=exchange,
        interval=interval,
        from_date=from_date,
        to_date=to_date,
    )
    raw = session.fetch_candles_for_symbol(
        symbol=symbol, exchange=exchange, interval=interval,
        from_dt=from_dt, to_dt=to_dt,
    )
    if raw.empty:
        raise RuntimeError(f"No candle data returned for {symbol} ({from_date} -> {to_date})")

    raw = raw.set_index("datetime").sort_index()
    return compute_indicators(raw)


def _main() -> None:
    """CLI entry point: ``python -m app.backtest.runner``."""
    from app.strategies import ALL_STRATEGIES

    parser = argparse.ArgumentParser(
        description="Run strategy backtests on synthetic or real historical data.",
    )
    parser.add_argument("--symbol", default="NIFTY")
    parser.add_argument("--strategy", default="all", help="Strategy name or 'all'")
    parser.add_argument("--capital", type=float, default=25_000.0)
    parser.add_argument("--risk-pct", type=float, default=1.0)
    parser.add_argument("--lot-size", type=int, default=1)
    parser.add_argument("--walk-forward", action="store_true")
    parser.add_argument(
        "--from", dest="from_date", default=None,
        help="Start date YYYY-MM-DD (uses Angel API). Omit for synthetic data.",
    )
    parser.add_argument(
        "--to", dest="to_date", default=None,
        help="End date YYYY-MM-DD (uses Angel API). Omit for synthetic data.",
    )
    parser.add_argument("--interval", default="5m", help="Candle interval (e.g. 1m, 5m, 15m, 1d)")
    parser.add_argument("--exchange", default="NSE", help="Exchange segment (NSE, NFO, etc.)")
    parser.add_argument(
        "--trailing-atr", type=float, default=0.0,
        help="ATR trailing stop multiplier (e.g. 1.5). 0 = disabled.",
    )
    parser.add_argument(
        "--params", default=None,
        help='JSON dict of strategy params, e.g. \'{"atr_mult": 1.2, "period": 7}\'',
    )
    args = parser.parse_args()

    # Load data: real from Angel API or synthetic
    if args.from_date and args.to_date:
        df = _fetch_real_data(
            args.symbol, args.exchange, args.interval, args.from_date, args.to_date,
        )
    else:
        df = _build_sample_df()

    # Parse optional custom params
    custom_params: dict = {}
    if args.params:
        import json as _json
        custom_params = _json.loads(args.params)

    strategies: list[Strategy] = (
        [cls(**custom_params) for cls in ALL_STRATEGIES]
        if args.strategy == "all"
        else [cls(**custom_params) for cls in ALL_STRATEGIES if cls.name == args.strategy]
    )
    if not strategies:
        log.error(
            "backtest_strategy_not_found",
            requested=args.strategy,
            available=[c.name for c in ALL_STRATEGIES],
        )
        return

    log.info(
        "backtest_started",
        strategy=args.strategy,
        symbol=args.symbol,
        from_date=str(df.index[0].date()),
        to_date=str(df.index[-1].date()),
    )

    if args.walk_forward:
        results = walk_forward(
            df, strategies, symbol=args.symbol,
            capital=args.capital, lot_size=args.lot_size, risk_pct=args.risk_pct,
            trailing_atr_mult=args.trailing_atr,
        )
    else:
        results = run_backtest(
            df, strategies, symbol=args.symbol,
            capital=args.capital, lot_size=args.lot_size, risk_pct=args.risk_pct,
            trailing_atr_mult=args.trailing_atr,
        )

    for r in results:
        log.info("backtest_summary", summary=r.summary())


if __name__ == "__main__":
    _main()
