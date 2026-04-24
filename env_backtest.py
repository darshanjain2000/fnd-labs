"""Run a backtest using symbols and strategy settings from .env.

Usage:
    python env_backtest.py --from 2026-03-24 --to 2026-04-24

This script intentionally reads:
- symbols from WATCHLIST
- strategies from ENABLED_STRATEGIES
- gates/thresholds from .env Settings

Only the date window is required.
"""
from __future__ import annotations

import argparse
from datetime import datetime

from batch_backtest import (
    REPORTS_DIR,
    RESULTS_FIELDS,
    TRADES_FIELDS,
    _ensure_csv,
    _run_symbol,
)

from app.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.db import init_db

log = get_logger(__name__)


def _main() -> None:
    """CLI entry point for env-driven backtesting."""
    parser = argparse.ArgumentParser(
        description="Run backtest from .env watchlist/strategies. Only --from/--to are required.",
    )
    parser.add_argument("--from", dest="from_date", required=True, help="Start date YYYY-MM-DD")
    parser.add_argument("--to", dest="to_date", required=True, help="End date YYYY-MM-DD")
    parser.add_argument("--interval", default="5m", help="Candle interval (default: 5m)")
    parser.add_argument("--capital", type=float, default=25_000.0, help="Starting capital")
    parser.add_argument("--lot-size", type=int, default=1, help="Lot size")
    parser.add_argument("--risk-pct", type=float, default=1.0, help="Risk percentage")
    parser.add_argument("--trailing-atr", type=float, default=0.0, help="ATR trailing stop multiplier")
    parser.add_argument(
        "--mode",
        choices=["orchestrator", "live-parity"],
        default="orchestrator",
        help="Backtest mode: full orchestrator parity (default) or live-parity ensemble mode",
    )
    args = parser.parse_args()

    configure_logging()
    init_db()
    s = get_settings()

    watchlist_pairs = s.watchlist_pairs()
    if not watchlist_pairs:
        raise SystemExit("WATCHLIST is empty in .env")

    run_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    results_csv = REPORTS_DIR / "results.csv"
    trades_csv = REPORTS_DIR / "trades.csv"
    _ensure_csv(results_csv, RESULTS_FIELDS)
    _ensure_csv(trades_csv, TRADES_FIELDS)

    log.info(
        "env_backtest_started",
        from_date=args.from_date,
        to_date=args.to_date,
        interval=args.interval,
        symbols=[f"{sym}:{exch}" for sym, exch in watchlist_pairs],
        enabled_strategies=s.strategy_list(),
        mode=args.mode,
        min_strategy_agreement=s.min_strategy_agreement,
        min_signal_confidence=s.min_signal_confidence,
        signal_memory_ticks=s.signal_memory_ticks,
    )

    print(
        f"Env backtest: {len(watchlist_pairs)} symbols | "
        f"{args.from_date} -> {args.to_date} | interval={args.interval} | mode={args.mode}"
    )
    print(f"Using .env WATCHLIST={s.watchlist}")
    print(f"Using .env ENABLED_STRATEGIES={s.enabled_strategies}")
    print(f"Results -> {results_csv}")
    print(f"Trades  -> {trades_csv}")
    print("-" * 60)

    for idx, (symbol, exchange) in enumerate(watchlist_pairs, 1):
        print(f"[{idx}/{len(watchlist_pairs)}] {symbol}:{exchange} ...", flush=True)
        _run_symbol(
            symbol=symbol,
            exchange=exchange,
            interval=args.interval,
            from_date=args.from_date,
            to_date=args.to_date,
            capital=args.capital,
            lot_size=args.lot_size,
            risk_pct=args.risk_pct,
            trailing_atr=args.trailing_atr,
            walk_forward=False,
            run_at=run_at,
            results_csv=results_csv,
            trades_csv=trades_csv,
            use_optimized=False,
            live_parity=(args.mode == "live-parity"),
            orchestrator_parity=(args.mode == "orchestrator"),
            ensemble=0,
            min_confidence=None,
        )

    print("-" * 60)
    print(f"Done. Results saved to {results_csv} and {trades_csv}")
    log.info("env_backtest_completed", run_at=run_at, symbols=len(watchlist_pairs))


if __name__ == "__main__":
    _main()
