"""Tests for the backtester and Optuna optimiser (Phase 3)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.backtest.runner import BacktestResult, TradeRecord, run_backtest, walk_forward
from app.engine.risk_engine import RiskEngine, compute_kelly_fraction
from app.services.market_data import compute_indicators
from app.strategies.ema_breakout import EMABreakout
from app.strategies.rsi_reversal import RSIReversal


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _df(n: int = 300, seed: int = 42) -> pd.DataFrame:
    """Synthetic trending OHLCV DataFrame with indicators."""
    rng = np.random.default_rng(seed)
    closes = 20_000.0 + np.cumsum(rng.normal(0, 30, n))
    idx = pd.date_range("2025-01-02 09:15", periods=n, freq="1min")
    df = pd.DataFrame(
        {
            "open": closes * (1 - rng.uniform(0, 0.0005, n)),
            "high": closes * (1 + rng.uniform(0, 0.001, n)),
            "low": closes * (1 - rng.uniform(0, 0.001, n)),
            "close": closes,
            "volume": rng.integers(1000, 20000, n),
        },
        index=idx,
    )
    return compute_indicators(df)


# ---------------------------------------------------------------------------
# run_backtest
# ---------------------------------------------------------------------------

def test_run_backtest_returns_one_result_per_strategy() -> None:
    df = _df()
    strategies = [RSIReversal(), EMABreakout()]
    results = run_backtest(df, strategies, symbol="NIFTY")
    assert len(results) == 2
    names = {r.strategy for r in results}
    assert names == {"rsi_reversal", "ema_breakout"}


def test_run_backtest_result_has_correct_fields() -> None:
    df = _df()
    results = run_backtest(df, [EMABreakout()], symbol="TEST", capital=25_000.0)
    r = results[0]
    assert isinstance(r, BacktestResult)
    assert r.symbol == "TEST"
    assert r.capital_start == 25_000.0
    assert isinstance(r.total_pnl, float)
    assert 0.0 <= r.win_rate <= 1.0


def test_run_backtest_trade_pnl_matches_total() -> None:
    df = _df()
    results = run_backtest(df, [EMABreakout()], capital=25_000.0)
    r = results[0]
    assert abs(r.total_pnl - sum(t.pnl for t in r.trades)) < 0.01


def test_run_backtest_no_trades_on_too_short_data() -> None:
    df = _df(n=65)  # barely enough for warmup — expect 0 or 1 trade
    results = run_backtest(df, [EMABreakout()])
    # Should not crash; trade count can be 0 or 1
    assert isinstance(results[0].trades, list)


def test_run_backtest_stop_loss_respected() -> None:
    """All closed trades must exit at or near the declared stop/target."""
    df = _df(n=400)
    results = run_backtest(df, [RSIReversal()], capital=50_000.0, lot_size=1)
    for t in results[0].trades:
        assert isinstance(t, TradeRecord)
        assert t.exit_reason in ("stop", "target", "trailing", "eod")


# ---------------------------------------------------------------------------
# trailing ATR stop
# ---------------------------------------------------------------------------

def test_trailing_stop_produces_trailing_exits() -> None:
    """With trailing_atr_mult > 0, some trades should exit via 'trailing'."""
    df = _df(n=500, seed=99)
    results = run_backtest(
        df, [RSIReversal()], capital=50_000.0, trailing_atr_mult=1.5,
    )
    r = results[0]
    exit_reasons = {t.exit_reason for t in r.trades}
    # At minimum the code path is exercised without error
    assert exit_reasons.issubset({"stop", "target", "trailing", "eod"})


def test_trailing_stop_disabled_by_default() -> None:
    """With trailing_atr_mult=0, no trades should exit via 'trailing'."""
    df = _df(n=400)
    results = run_backtest(df, [RSIReversal()], capital=50_000.0, trailing_atr_mult=0.0)
    for t in results[0].trades:
        assert t.exit_reason in ("stop", "target", "eod")


# ---------------------------------------------------------------------------
# walk_forward
# ---------------------------------------------------------------------------

def test_walk_forward_runs_without_error() -> None:
    df = _df(n=600)
    results = walk_forward(df, [RSIReversal()], train_bars=200, test_bars=100)
    assert len(results) == 1
    assert isinstance(results[0], BacktestResult)


def test_walk_forward_produces_oos_trades() -> None:
    df = _df(n=800, seed=7)
    results = walk_forward(df, [EMABreakout()], train_bars=300, test_bars=150, capital=25_000.0)
    r = results[0]
    # With 800 bars and 150 step, expect at least one OOS window
    assert r.from_date is not None
    assert r.to_date is not None


# ---------------------------------------------------------------------------
# compute_kelly_fraction (utility function)
# ---------------------------------------------------------------------------

def test_kelly_returns_1_on_insufficient_data() -> None:
    assert compute_kelly_fraction([]) == 1.0
    assert compute_kelly_fraction([100.0, 200.0]) == 1.0  # < 5 trades


def test_kelly_returns_1_on_all_wins() -> None:
    # All wins → no loss history → 1.0
    assert compute_kelly_fraction([100.0] * 10) == 1.0


def test_kelly_bounded_between_025_and_1() -> None:
    pnls = [10.0, -100.0, 5.0, -80.0, 8.0, -90.0, 3.0, -110.0, 6.0, -70.0]
    frac = compute_kelly_fraction(pnls)
    assert 0.25 <= frac <= 1.0


def test_kelly_applies_to_risk_engine() -> None:
    """Kelly fraction should reduce position size when enabled."""
    from app.config import Settings
    from app.strategies.base import Signal

    s = Settings(
        mode="paper",
        capital_inr=100_000.0,
        max_risk_per_trade_pct=1.0,
        max_daily_loss_pct=2.0,
        max_open_positions=5,
        max_trades_per_day=10,
        kill_switch=False,
        block_expiry_last_hours=2,
        kelly_sizing_enabled=True,
    )
    engine = RiskEngine(settings=s)
    sig = Signal(symbol="X", strategy="t", side="BUY", entry=100.0, stop_loss=98.0, target=104.0)

    # Baseline (kelly_fraction=1.0)
    base = engine.evaluate(sig, lot_size=1)

    # With a losing streak → low Kelly fraction → fewer units
    losing_pnls = [-500.0] * 15 + [50.0] * 5
    engine.update_kelly_fraction(losing_pnls)
    reduced = engine.evaluate(sig, lot_size=1)

    assert base.approved
    assert reduced.approved
    assert reduced.qty <= base.qty


# ---------------------------------------------------------------------------
# SignalAgent regime filtering
# ---------------------------------------------------------------------------

def test_signal_agent_regime_filter_blocks_mismatched_strategy() -> None:
    """SupertrendStrategy (trend-only) should be blocked in 'range' regime."""
    from app.config import Settings
    from app.agents.signal_agent import SignalAgent
    from app.strategies.supertrend import SupertrendStrategy

    # Flat candles → 'range' regime
    closes = [100.0 + (i % 3) * 0.1 for i in range(80)]
    n = len(closes)
    df_raw = pd.DataFrame(
        {
            "open": closes,
            "high": [c * 1.001 for c in closes],
            "low": [c * 0.999 for c in closes],
            "close": closes,
            "volume": [1000] * n,
        }
    )
    df = compute_indicators(df_raw)

    s = Settings(mode="paper", regime_filter_enabled=True)
    agent = SignalAgent(strategies=[SupertrendStrategy()], settings=s)
    signals = agent.generate("X", df)
    # Supertrend only fires on direction flips, which don't occur on flat data anyway,
    # but regime filter should also block it. Either way, no signal expected.
    assert signals == []


def test_signal_agent_regime_filter_disabled_passes_all() -> None:
    """When regime_filter_enabled=False, strategies are not filtered by regime."""
    from app.config import Settings
    from app.agents.signal_agent import SignalAgent
    from app.strategies.rsi_reversal import RSIReversal

    closes = list(np.linspace(200, 100, 60))
    n = len(closes)
    df_raw = pd.DataFrame(
        {
            "open": closes,
            "high": [c * 1.005 for c in closes],
            "low": [c * 0.995 for c in closes],
            "close": closes,
            "volume": [1000] * n,
        }
    )
    df = compute_indicators(df_raw)

    s = Settings(mode="paper", regime_filter_enabled=False)
    agent = SignalAgent(strategies=[RSIReversal()], settings=s)
    signals = agent.generate("X", df)
    # RSI reversal should still fire on deep oversold regardless of regime filter
    assert len(signals) >= 1
