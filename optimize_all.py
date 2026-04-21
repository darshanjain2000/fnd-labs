"""Batch optimizer for all 7 strategies on a given symbol.

Runs Optuna optimization for each strategy and writes a single combined YAML
to ``config/params_{SYMBOL}.yaml``. This file is automatically picked up by
the live trading pipeline (via ``SignalAgent``) when ``main.py`` starts.

Usage::

    # Optimize using the last 5 years of data (default):
    python optimize_all.py --symbol NIFTY

    # Override date range:
    python optimize_all.py --symbol NIFTY --from 2024-01-01 --to 2025-01-01

    # Fewer trials for a quick test:
    python optimize_all.py --symbol HSCL --trials 50
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

STRATEGIES: list[str] = [
    "rsi_reversal",
    "ema_breakout",
    "vwap_pullback",
    "supertrend",
    "macd_divergence",
    "bollinger_squeeze",
    "orb_breakout",
]

CONFIG_DIR = Path(__file__).parent / "config"
_DEFAULT_LOOKBACK_YEARS = 5


def _default_date_range() -> tuple[str, str]:
    """Return (from_date, to_date) strings covering the last 5 years.

    Returns:
        Tuple of ISO date strings (from_date, to_date).
    """
    today = date.today()
    from_date = today - timedelta(days=_DEFAULT_LOOKBACK_YEARS * 365)
    return from_date.isoformat(), today.isoformat()


def _run_optimizer(
    symbol: str,
    strategy: str,
    from_date: str,
    to_date: str,
    interval: str,
    trials: int,
    tmp_path: Path,
) -> None:
    """Run the Optuna optimizer for a single strategy, writing output to *tmp_path*.

    Args:
        symbol: NSE trading symbol.
        strategy: Strategy name to optimize.
        from_date: Start date (ISO format).
        to_date: End date (ISO format).
        interval: Candle interval (e.g. "5m").
        trials: Number of Optuna trials.
        tmp_path: Temporary output YAML path for this strategy.
    """
    cmd = [
        sys.executable, "-m", "app.backtest.optimize",
        "--strategy", strategy,
        "--symbol", symbol,
        "--from", from_date,
        "--to", to_date,
        "--interval", interval,
        "--trials", str(trials),
        "--output", str(tmp_path),
    ]
    subprocess.run(cmd, check=True)


def _load_best_params(path: Path) -> dict:
    """Load the best_params dict from a strategy YAML result file.

    Args:
        path: Path to the YAML file written by the optimizer.

    Returns:
        Dict with keys ``best_params``, ``best_value``, ``metric``.
    """
    import yaml  # type: ignore

    with path.open() as fh:
        raw = yaml.safe_load(fh)
    # The optimizer writes a list of results; take the first entry
    if isinstance(raw, list) and raw:
        return raw[0]
    if isinstance(raw, dict):
        return raw
    return {}


def main() -> None:
    """Parse CLI args, run all strategies, and write the combined params file."""
    default_from, default_to = _default_date_range()

    parser = argparse.ArgumentParser(
        description="Optimize all strategies for a symbol and save combined params YAML."
    )
    parser.add_argument("--symbol", required=True, help="NSE trading symbol (e.g. NIFTY).")
    parser.add_argument(
        "--from", dest="from_date", default=default_from,
        help=f"Start date YYYY-MM-DD (default: {default_from}, i.e. {_DEFAULT_LOOKBACK_YEARS} years ago).",
    )
    parser.add_argument(
        "--to", dest="to_date", default=default_to,
        help=f"End date YYYY-MM-DD (default: {default_to}, i.e. today).",
    )
    parser.add_argument("--interval", default="5m", help="Candle interval (default: 5m).")
    parser.add_argument("--trials", type=int, default=100, help="Optuna trials per strategy (default: 100).")
    args = parser.parse_args()

    CONFIG_DIR.mkdir(exist_ok=True)
    combined: dict[str, dict] = {}

    for strategy in STRATEGIES:
        print(f"\n=== Optimizing {strategy} for {args.symbol} ({args.from_date} → {args.to_date}) ===")
        tmp_path = CONFIG_DIR / f"_tmp_{args.symbol.lower()}_{strategy}.yaml"
        try:
            _run_optimizer(
                symbol=args.symbol,
                strategy=strategy,
                from_date=args.from_date,
                to_date=args.to_date,
                interval=args.interval,
                trials=args.trials,
                tmp_path=tmp_path,
            )
            combined[strategy] = _load_best_params(tmp_path)
        finally:
            # Always clean up temporary per-strategy file
            if tmp_path.exists():
                tmp_path.unlink()

    output_path = CONFIG_DIR / f"params_{args.symbol.lower()}.yaml"
    import yaml  # type: ignore
    with output_path.open("w") as fh:
        yaml.dump(combined, fh, default_flow_style=False, sort_keys=True)

    print(f"\nOptimized parameters saved: {output_path}")
    print(f"Strategies: {', '.join(combined.keys())}")
    print("The live trading pipeline will automatically use these params for", args.symbol)


if __name__ == "__main__":
    main()

