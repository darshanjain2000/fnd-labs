"""Optuna-based hyperparameter optimisation for trading strategies.

Searches strategy parameters to maximise the Sortino ratio on an OOS test
window. Best parameters are printed and optionally saved to a YAML file.

Usage::

    python -m app.backtest.optimize \\
        --strategy ema_breakout \\
        --trials 50 \\
        --output config/optimized_params.yaml
"""
from __future__ import annotations

import argparse
import json
from typing import Any

import numpy as np
import pandas as pd

from app.backtest.runner import BacktestResult, run_backtest
from app.core.logging import get_logger
from app.services.market_data import compute_indicators
from app.strategies.base import Strategy

# Re-use the real data fetcher from the backtest runner
from app.backtest.runner import _fetch_real_data

log = get_logger(__name__)

try:
    import optuna  # type: ignore

    optuna.logging.set_verbosity(optuna.logging.WARNING)
except ImportError:  # pragma: no cover
    optuna = None  # type: ignore


# ---------------------------------------------------------------------------
# Parameter search spaces per strategy
# ---------------------------------------------------------------------------

_PARAM_SPACES: dict[str, dict[str, Any]] = {
    "rsi_reversal": {
        "oversold": ("float", 20.0, 40.0),
        "overbought": ("float", 60.0, 80.0),
        "atr_mult": ("float", 1.0, 3.0),
    },
    "ema_breakout": {
        "atr_mult": ("float", 0.5, 3.0),
    },
    "vwap_pullback": {
        "tolerance_pct": ("float", 0.1, 0.5),
        "atr_mult": ("float", 0.5, 2.5),
    },
    "supertrend": {
        "atr_mult": ("float", 1.5, 5.0),
        "period": ("int", 7, 20),
    },
    "macd_divergence": {
        "atr_mult": ("float", 1.0, 3.0),
        "reward_ratio": ("float", 1.5, 4.0),
    },
    "bollinger_squeeze": {
        "squeeze_pct": ("float", 1.0, 4.0),
        "atr_mult": ("float", 1.0, 3.0),
    },
    "orb_breakout": {
        "orb_minutes": ("int", 15, 60),
    },
}


def _suggest_params(trial: "optuna.Trial", space: dict[str, Any]) -> dict[str, Any]:
    """Sample one trial's hyperparameters from *space*.

    Args:
        trial: Active Optuna trial.
        space: Dict mapping parameter name to (kind, low, high).

    Returns:
        Dict of sampled parameter values.
    """
    params: dict[str, Any] = {}
    for name, spec in space.items():
        kind, low, high = spec
        if kind == "float":
            params[name] = trial.suggest_float(name, low, high)
        elif kind == "int":
            params[name] = trial.suggest_int(name, int(low), int(high))
    return params


def _make_strategy(strategy_class: type[Strategy], params: dict[str, Any]) -> Strategy:
    """Instantiate *strategy_class* with *params*.

    Args:
        strategy_class: Strategy subclass to instantiate.
        params: Keyword arguments forwarded to the constructor.

    Returns:
        Configured strategy instance.
    """
    return strategy_class(**params)


def _build_sample_df(n: int = 1200) -> pd.DataFrame:
    """Synthetic OHLCV data for optimisation (deterministic seed).

    Args:
        n: Number of 1-minute candles.

    Returns:
        DataFrame with indicators already computed.
    """
    rng = np.random.default_rng(0)
    closes = 20_000.0 + np.cumsum(rng.normal(0, 50, n))
    idx = pd.date_range("2025-01-02 09:15", periods=n, freq="1min")
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


def optimize(
    strategy_class: type[Strategy],
    df: pd.DataFrame | None = None,
    n_trials: int = 50,
    metric: str = "sortino",
    train_frac: float = 0.7,
    capital: float = 25_000.0,
    lot_size: int = 1,
    risk_pct: float = 1.0,
    symbol: str | None = None,
    storage_path: str = "sqlite:///config/optuna_studies.db",
) -> dict[str, Any]:
    """Search for optimal hyperparameters using Optuna.

    The dataset is split train/OOS at *train_frac*. The objective function
    evaluates the strategy on the OOS portion only (prevents overfitting).
    Trials are persisted to *storage_path* so re-runs accumulate rather than
    restart (Walk-Forward warm-starting).

    Args:
        strategy_class: Strategy class to optimise (must be in _PARAM_SPACES).
        df: OHLCV DataFrame with indicators. Defaults to synthetic data.
        n_trials: Number of Optuna trials (default 50).
        metric: Objective metric — "sortino" (default), "sharpe", or "win_rate".
        train_frac: Fraction of data used as training window (OOS = 1-train_frac).
        capital: Starting capital in INR.
        lot_size: F&O lot size.
        risk_pct: Per-trade risk percentage.
        symbol: NSE symbol used to scope the Optuna study name. When provided
            the study is named ``"{strategy}__{symbol}"`` so different symbols
            maintain independent trial histories.
        storage_path: SQLAlchemy URL for the Optuna study store. Defaults to
            a SQLite file at ``config/optuna_studies.db`` (relative to cwd).
            Set to ``None`` to fall back to in-memory (testing only).

    Returns:
        Dict with "best_params", "best_value", and "strategy" keys.

    Raises:
        ImportError: If optuna is not installed.
        KeyError: If strategy_class.name is not in _PARAM_SPACES.
    """
    if optuna is None:
        raise ImportError("optuna is required for optimisation: pip install optuna")

    strat_name = strategy_class.name
    if strat_name not in _PARAM_SPACES:
        raise KeyError(f"No parameter space defined for strategy '{strat_name}'")

    if df is None:
        df = _build_sample_df()

    split = int(len(df) * train_frac)
    oos_df = df.iloc[split:]
    space = _PARAM_SPACES[strat_name]

    def objective(trial: "optuna.Trial") -> float:
        """Optuna objective: evaluate strategy on OOS data.

        Args:
            trial: Active Optuna trial.

        Returns:
            OOS metric value (higher is better).
        """
        params = _suggest_params(trial, space)
        strat = _make_strategy(strategy_class, params)
        results: list[BacktestResult] = run_backtest(
            oos_df,
            strategies=[strat],
            symbol="OPT",
            capital=capital,
            lot_size=lot_size,
            risk_pct=risk_pct,
        )
        if not results or not results[0].trades:
            return -999.0
        r = results[0]
        # Require a meaningful sample size for any metric to avoid
        # overfitting to 1-3 lucky trades.
        if len(r.trades) < 10:
            return -999.0
        if metric == "win_rate":
            return r.win_rate
        return r.sortino if metric == "sortino" else r.sharpe

    study_name = f"{strat_name}__{symbol}" if symbol else strat_name
    study = optuna.create_study(
        direction="maximize",
        storage=storage_path,
        study_name=study_name,
        load_if_exists=True,
    )
    study.optimize(objective, n_trials=n_trials, show_progress_bar=False)

    best = study.best_trial
    log.info(
        "optuna_best",
        strategy=strat_name,
        metric=metric,
        value=round(best.value, 4),
        params=best.params,
    )
    return {
        "strategy": strat_name,
        "metric": metric,
        "best_value": round(best.value, 4),
        "best_params": best.params,
    }


def save_params(results: list[dict[str, Any]], path: str) -> None:
    """Persist optimisation results to a YAML or JSON file.

    Args:
        results: List of result dicts from :func:`optimize`.
        path: Output file path. Suffix determines format:
              ``.yaml``/``.yml`` → YAML; anything else → JSON.
    """
    if path.endswith((".yaml", ".yml")):
        try:
            import yaml  # type: ignore

            with open(path, "w") as fh:
                yaml.dump(results, fh, default_flow_style=False)
        except ImportError:  # pragma: no cover
            log.warning("pyyaml_not_installed_falling_back_to_json")
            path = path.rsplit(".", 1)[0] + ".json"
            with open(path, "w") as fh:
                json.dump(results, fh, indent=2)
    else:
        with open(path, "w") as fh:
            json.dump(results, fh, indent=2)
    log.info("optuna_params_saved", path=path, strategies=[r["strategy"] for r in results])


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _main() -> None:
    """CLI: ``python -m app.backtest.optimize``."""
    from app.strategies import ALL_STRATEGIES

    parser = argparse.ArgumentParser(description="Optimise strategy hyperparameters with Optuna.")
    parser.add_argument("--strategy", default="all")
    parser.add_argument("--trials", type=int, default=50)
    parser.add_argument("--metric", default="sortino", choices=["sortino", "sharpe", "win_rate"])
    parser.add_argument("--output", default="config/optimized_params.yaml")
    parser.add_argument("--capital", type=float, default=25_000.0)
    parser.add_argument("--risk-pct", type=float, default=1.0)
    parser.add_argument(
        "--symbol", default=None,
        help="NSE symbol (e.g. NIFTY). When provided with --from/--to, uses real data.",
    )
    parser.add_argument(
        "--from", dest="from_date", default=None,
        help="Start date YYYY-MM-DD (uses Angel API for real data).",
    )
    parser.add_argument(
        "--to", dest="to_date", default=None,
        help="End date YYYY-MM-DD (uses Angel API for real data).",
    )
    parser.add_argument("--interval", default="5m", help="Candle interval (e.g. 1m, 5m, 15m)")
    parser.add_argument("--exchange", default="NSE", help="Exchange segment (NSE, NFO, etc.)")
    args = parser.parse_args()

    target_classes = (
        [cls for cls in ALL_STRATEGIES if cls.name in _PARAM_SPACES]
        if args.strategy == "all"
        else [cls for cls in ALL_STRATEGIES if cls.name == args.strategy]
    )
    if not target_classes:
        log.error("optimize_strategy_not_found", requested=args.strategy)
        return

    # Load data: real from Angel API or synthetic
    if args.symbol and args.from_date and args.to_date:
        log.info(
            "optimize_fetching_real_data",
            symbol=args.symbol,
            from_date=args.from_date,
            to_date=args.to_date,
            interval=args.interval,
        )
        df = _fetch_real_data(
            args.symbol, args.exchange, args.interval,
            args.from_date, args.to_date,
        )
    else:
        log.info("optimize_using_synthetic_data")
        df = _build_sample_df()

    all_results: list[dict[str, Any]] = []
    for cls in target_classes:
        result = optimize(
            cls, df=df, n_trials=args.trials, metric=args.metric,
            capital=args.capital, risk_pct=args.risk_pct,
            symbol=args.symbol,
        )
        all_results.append(result)
        log.info("optimize_result", result=result)

    if args.output:
        import os
        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
        save_params(all_results, args.output)


if __name__ == "__main__":
    _main()
