"""Batch optimizer — runs optimize_all.py for a list of symbols.

Optimizes all 7 strategies per symbol, writing results to
``config/params_{symbol}.yaml``. These are then auto-loaded by
``batch_backtest.py --use-optimized``.

Usage::

    # All 18 working NSE20 symbols, last 2 years, 30 trials per strategy:
    python batch_optimize.py --watchlist nse20 --from 2024-04-22 --to 2026-04-22 --trials 30

    # Specific symbols:
    python batch_optimize.py --symbols INOXWIND PGEL --from 2024-04-22 --to 2026-04-22 --trials 50
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import os
from datetime import date, timedelta
from pathlib import Path

# Symbols with working Angel API tokens from the nse20 watchlist
WATCHLISTS: dict[str, list[str]] = {
    "nse20": [
        "ADANIENT",
        "VEDL",
        "BSE",
        "ADANIPORTS",
        "HAL",
        "JSWSTEEL",
        "IRCTC",
        "BAJAJFINSV",
        "INOXWIND",
        "GRAVITA",
        "PGEL",
        "IFCI",
        "RECLTD",
        "HINDCOPPER",
        "JINDALSAW",
        "MAZDOCK",
        "ZENTEC",
        "SUZLON",
    ],
}


def _default_date_range() -> tuple[str, str]:
    """Return (from_date, to_date) covering the last 2 years.

    Returns:
        Tuple of ISO date strings.
    """
    today = date.today()
    from_date = today - timedelta(days=2 * 365)
    return from_date.isoformat(), today.isoformat()


def _run_optimize_for_symbol(
    symbol: str,
    from_date: str,
    to_date: str,
    interval: str,
    trials: int,
) -> bool:
    """Run optimize_all.py for a single symbol.

    Args:
        symbol: NSE trading symbol.
        from_date: Start date (ISO format).
        to_date: End date (ISO format).
        interval: Candle interval (e.g. "5m").
        trials: Number of Optuna trials per strategy.

    Returns:
        True if the subprocess exited with code 0, False otherwise.
    """
    # Always use the venv Python if available
    venv_python = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.venv', 'Scripts', 'python.exe')
    python_exec = venv_python if os.path.exists(venv_python) else sys.executable
    cmd = [
        python_exec, "optimize_all.py",
        "--symbol", symbol,
        "--from", from_date,
        "--to", to_date,
        "--interval", interval,
        "--trials", str(trials),
    ]
    result = subprocess.run(cmd)
    return result.returncode == 0


def _main() -> None:
    """CLI entry point for batch optimization."""
    parser = argparse.ArgumentParser(
        description="Batch-optimize all strategies for multiple symbols.",
    )
    group = parser.add_mutually_exclusive_group(required=False)
    group.add_argument("--symbols", nargs="+", metavar="SYMBOL")
    group.add_argument("--watchlist", choices=list(WATCHLISTS.keys()), default="nse20")
    parser.add_argument("--from", dest="from_date", default=None)
    parser.add_argument("--to", dest="to_date", default=None)
    parser.add_argument("--interval", default="5m")
    parser.add_argument("--trials", type=int, default=100)
    args = parser.parse_args()

    symbols = args.symbols if args.symbols else WATCHLISTS[args.watchlist]

    if args.from_date and args.to_date:
        from_date, to_date = args.from_date, args.to_date
    else:
        from_date, to_date = _default_date_range()

    print(
        f"Batch optimize: {len(symbols)} symbols | "
        f"{from_date} -> {to_date} | interval={args.interval} | trials={args.trials}"
    )
    print("-" * 60)

    ok, failed = [], []
    for idx, symbol in enumerate(symbols, 1):
        print(f"\n[{idx}/{len(symbols)}] Optimizing {symbol} ...", flush=True)
        success = _run_optimize_for_symbol(symbol, from_date, to_date, args.interval, args.trials)
        if success:
            ok.append(symbol)
            print(f"  [OK] {symbol} -> config/params_{symbol.lower()}.yaml")
        else:
            failed.append(symbol)
            print(f"  [FAIL] {symbol}: optimizer exited with non-zero code")

    print("\n" + "-" * 60)
    print(f"Done. {len(ok)} succeeded, {len(failed)} failed.")
    if failed:
        print(f"Failed symbols: {', '.join(failed)}")


if __name__ == "__main__":
    _main()
