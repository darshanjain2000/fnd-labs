"""Batch backtester — runs all strategies on a list of symbols.

Results are appended to two CSV files in ``backtest/reports/``:
  - ``results.csv``  : one summary row per (symbol × strategy)
  - ``trades.csv``   : one row per individual simulated trade

Usage::

    python batch_backtest.py --symbols NIFTY SENSEX \\
        --from 2025-04-01 --to 2026-04-01 --interval 5m

    # Or use the built-in NSE watchlist:
    python batch_backtest.py --watchlist nse20 --from 2025-04-01 --to 2026-04-01
"""
from __future__ import annotations

import argparse
import csv
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

# ---------------------------------------------------------------------------
# Pre-defined watchlists
# ---------------------------------------------------------------------------

WATCHLISTS: dict[str, list[str]] = {
    "nse20": [
        "ADANIENT",
        "VEDL",
        "BSE",
        "ADANIPORTS",
        "TATAMOTORS",
        "HAL",
        "JSWSTEEL",
        "IRCTC",
        "ZOMATO",
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

REPORTS_DIR = Path(__file__).parent / "backtest" / "reports"

RESULTS_FIELDS = [
    "run_at",
    "symbol",
    "strategy",
    "from",
    "to",
    "trades",
    "win_rate",
    "total_pnl",
    "capital_end",
    "sharpe",
    "sortino",
    "max_drawdown_pct",
]

TRADES_FIELDS = [
    "run_at",
    "symbol",
    "strategy",
    "side",
    "entry",
    "exit",
    "stop_loss",
    "target",
    "qty",
    "pnl",
    "bars_held",
    "exit_reason",
    "contributing_strategies",
]


def _ensure_csv(path: Path, fieldnames: list[str]) -> None:
    """Create the CSV with header row if it does not already exist.

    Args:
        path: Destination file path.
        fieldnames: CSV column names.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        with path.open("w", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames)
            writer.writeheader()


def _append_rows(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    """Append *rows* to the CSV at *path*.

    Args:
        path: Destination CSV path (must already have header).
        fieldnames: Column names (used to order values correctly).
        rows: List of dicts to write.
    """
    with path.open("a", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
        writer.writerows(rows)


def _default_date_range() -> tuple[str, str]:
    """Return a (from_date, to_date) covering the last 1 year.

    Returns:
        Tuple of ISO date strings.
    """
    today = date.today()
    from_date = today - timedelta(days=365)
    return from_date.isoformat(), today.isoformat()


def _run_symbol(
    symbol: str,
    exchange: str,
    interval: str,
    from_date: str,
    to_date: str,
    capital: float,
    lot_size: int,
    risk_pct: float,
    trailing_atr: float,
    walk_forward: bool,
    run_at: str,
    results_csv: Path,
    trades_csv: Path,
    use_optimized: bool = False,
    live_parity: bool = False,
    orchestrator_parity: bool = False,
    ensemble: int = 0,
    min_confidence: float | None = None,
) -> None:
    """Fetch candles, run all strategies, and persist results for one symbol.

    Args:
        symbol: NSE trading symbol.
        exchange: Exchange segment (e.g. "NSE").
        interval: Candle interval string (e.g. "5m").
        from_date: Start date ISO string.
        to_date: End date ISO string.
        capital: Starting capital in INR.
        lot_size: F&O lot size.
        risk_pct: Per-trade risk percentage.
        trailing_atr: ATR trailing stop multiplier (0 = off).
        walk_forward: Whether to use walk-forward validation.
        run_at: ISO timestamp string for the current batch run.
        results_csv: Path to summary CSV.
        trades_csv: Path to per-trade CSV.
        use_optimized: When True, load per-symbol best params from config/params_{symbol}.yaml.
        live_parity: When True, mirror main.py pipeline behavior:
            use enabled strategies from .env, optimized params, and .env
            ensemble thresholds.
        orchestrator_parity: When True, execute the full orchestrator entry
            decision path in simulation mode (signal -> validation -> risk -> execute).
        ensemble: If > 0, also run ensemble backtest requiring this many strategies to agree.
        min_confidence: Optional minimum confidence override for ensemble mode.
    """
    # Import here so startup errors don't kill the whole batch
    from app.backtest.runner import (
        _fetch_real_data,
        run_orchestrator_parity_backtest,
        run_backtest,
        run_ensemble_backtest,
        walk_forward as wf,
    )
    from app.strategies import ALL_STRATEGIES
    from app.core.logging import get_logger
    from app.core.optimized_params import load_params_for_symbol
    from app.config import get_settings

    log = get_logger(__name__)
    settings = get_settings()

    if orchestrator_parity:
        log.info("batch_backtest_mode", mode="orchestrator_parity", symbol=symbol)
    elif live_parity:
        log.info("batch_backtest_mode", mode="live_parity", symbol=symbol)
    elif use_optimized:
        log.info("batch_backtest_mode", mode="optimized_params", symbol=symbol)
    else:
        log.info("batch_backtest_mode", mode="baseline", symbol=symbol)

    log.info("batch_backtest_symbol_start", symbol=symbol, from_date=from_date, to_date=to_date)

    try:
        df = _fetch_real_data(symbol, exchange, interval, from_date, to_date)
    except Exception as exc:
        log.error("batch_backtest_fetch_failed", symbol=symbol, error=str(exc))
        print(f"  [SKIP] {symbol}: data fetch failed — {exc}", file=sys.stderr)
        return

    if live_parity:
        enabled = settings.strategy_list()
        selected = [cls for cls in ALL_STRATEGIES if not enabled or cls.name in enabled]
        sym_params = load_params_for_symbol(symbol)
        strategies = [cls(**sym_params.get(cls.name, {})) for cls in selected]
        print(
            "  [mode] live parity ON: enabled strategies from .env, "
            "optimized params auto-loaded when available"
        )
    elif use_optimized:
        sym_params = load_params_for_symbol(symbol)
        strategies = [cls(**sym_params.get(cls.name, {})) for cls in ALL_STRATEGIES]
        if sym_params:
            print(f"  [params] Loaded optimized params for {len(sym_params)} strategies")
        else:
            print(f"  [params] No optimized params found — using defaults")
    else:
        strategies = [cls() for cls in ALL_STRATEGIES]

    try:
        if orchestrator_parity:
            orch_result = run_orchestrator_parity_backtest(
                df,
                symbol=symbol,
                capital=capital,
                lot_size=lot_size,
                trailing_atr_mult=trailing_atr,
                settings=settings,
            )
            results = [orch_result]
        elif live_parity:
            eff_agreement = ensemble if ensemble > 0 else settings.min_strategy_agreement
            eff_confidence = (
                min_confidence
                if min_confidence is not None
                else settings.min_signal_confidence
            )
            ens_result = run_ensemble_backtest(
                df,
                strategies,
                symbol=symbol,
                capital=capital,
                lot_size=lot_size,
                risk_pct=risk_pct,
                trailing_atr_mult=trailing_atr,
                min_agreement=eff_agreement,
                min_confidence=eff_confidence,
                settings=settings,
            )
            results = [ens_result]
        elif walk_forward:
            results = wf(
                df, strategies, symbol=symbol,
                capital=capital, lot_size=lot_size, risk_pct=risk_pct,
                trailing_atr_mult=trailing_atr,
            )
        else:
            results = run_backtest(
                df, strategies, symbol=symbol,
                capital=capital, lot_size=lot_size, risk_pct=risk_pct,
                trailing_atr_mult=trailing_atr,
            )
    except Exception as exc:
        log.error("batch_backtest_run_failed", symbol=symbol, error=str(exc))
        print(f"  [SKIP] {symbol}: backtest run failed — {exc}", file=sys.stderr)
        return

    summary_rows: list[dict] = []
    trade_rows: list[dict] = []

    for r in results:
        s = r.summary()
        summary_rows.append(
            {
                "run_at": run_at,
                "symbol": s["symbol"],
                "strategy": s["strategy"],
                "from": s["from"],
                "to": s["to"],
                "trades": s["trades"],
                "win_rate": s["win_rate"],
                "total_pnl": s["total_pnl"],
                "capital_end": s["capital_end"],
                "sharpe": s["sharpe"],
                "sortino": s["sortino"],
                "max_drawdown_pct": s["max_drawdown_pct"],
            }
        )
        for t in r.trades:
            trade_rows.append(
                {
                    "run_at": run_at,
                    "symbol": t.symbol,
                    "strategy": t.strategy,
                    "side": t.side,
                    "entry": t.entry,
                    "exit": t.exit,
                    "stop_loss": t.stop_loss,
                    "target": t.target,
                    "qty": t.qty,
                    "pnl": t.pnl,
                    "bars_held": t.bars_held,
                    "exit_reason": t.exit_reason,
                    "contributing_strategies": t.contributing_strategies,
                }
            )

    # -- Ensemble backtest (if requested) --
    if ensemble > 0:
        ens_result = run_ensemble_backtest(
            df, strategies, symbol=symbol,
            capital=capital, lot_size=lot_size, risk_pct=risk_pct,
            trailing_atr_mult=trailing_atr,
            min_agreement=ensemble, min_confidence=min_confidence,
        )
        ens_s = ens_result.summary()
        summary_rows.append(
            {
                "run_at": run_at,
                "symbol": ens_s["symbol"],
                "strategy": ens_s["strategy"],
                "from": ens_s["from"],
                "to": ens_s["to"],
                "trades": ens_s["trades"],
                "win_rate": ens_s["win_rate"],
                "total_pnl": ens_s["total_pnl"],
                "capital_end": ens_s["capital_end"],
                "sharpe": ens_s["sharpe"],
                "sortino": ens_s["sortino"],
                "max_drawdown_pct": ens_s["max_drawdown_pct"],
            }
        )
        for t in ens_result.trades:
            trade_rows.append(
                {
                    "run_at": run_at,
                    "symbol": t.symbol,
                    "strategy": t.strategy,
                    "side": t.side,
                    "entry": t.entry,
                    "exit": t.exit,
                    "stop_loss": t.stop_loss,
                    "target": t.target,
                    "qty": t.qty,
                    "pnl": t.pnl,
                    "bars_held": t.bars_held,
                    "exit_reason": t.exit_reason,
                    "contributing_strategies": t.contributing_strategies,
                }
            )
        results.append(ens_result)

    _append_rows(results_csv, RESULTS_FIELDS, summary_rows)
    _append_rows(trades_csv, TRADES_FIELDS, trade_rows)

    total_trades = sum(r.summary()["trades"] for r in results)
    total_pnl = sum(r.summary()["total_pnl"] for r in results)
    print(
        f"  [OK] {symbol}: {total_trades} trades across {len(results)} strategies, "
        f"net P&L = {total_pnl:+,.2f}"
    )
    log.info(
        "batch_backtest_symbol_done",
        symbol=symbol,
        strategies=len(results),
        total_trades=total_trades,
        total_pnl=total_pnl,
    )


def _main() -> None:
    """CLI entry point for the batch backtester."""
    parser = argparse.ArgumentParser(
        description="Batch backtest all strategies across multiple symbols.",
    )
    group = parser.add_mutually_exclusive_group(required=False)
    group.add_argument(
        "--symbols",
        nargs="+",
        metavar="SYMBOL",
        help="One or more NSE symbols (e.g. --symbols NIFTY RELIANCE)",
    )
    group.add_argument(
        "--watchlist",
        choices=list(WATCHLISTS.keys()),
        help="Named watchlist of symbols (e.g. --watchlist nse20)",
    )
    parser.add_argument("--from", dest="from_date", default=None, help="Start date YYYY-MM-DD")
    parser.add_argument("--to", dest="to_date", default=None, help="End date YYYY-MM-DD")
    parser.add_argument("--interval", default="5m", help="Candle interval (e.g. 5m, 15m, 1d)")
    parser.add_argument("--exchange", default="NSE")
    parser.add_argument("--capital", type=float, default=25_000.0)
    parser.add_argument("--lot-size", type=int, default=1)
    parser.add_argument("--risk-pct", type=float, default=1.0)
    parser.add_argument("--trailing-atr", type=float, default=0.0)
    parser.add_argument("--walk-forward", action="store_true")
    parser.add_argument(
        "--use-optimized", action="store_true",
        help="Load per-symbol best params from config/params_{symbol}.yaml",
    )
    parser.add_argument(
        "--ensemble", type=int, default=0,
        help="If > 0, also run ensemble backtest requiring N strategies to agree (e.g. --ensemble 2)",
    )
    parser.add_argument(
        "--min-confidence", type=float, default=None,
        help="Optional minimum signal confidence override for ensemble/live-parity mode",
    )
    parser.add_argument(
        "--live-parity",
        action="store_true",
        help="Mirror main.py behavior: .env enabled strategies + .env gates + optimized params",
    )
    parser.add_argument(
        "--orchestrator-parity",
        action="store_true",
        help=(
            "Run simulation through orchestrator decision path "
            "(signal -> validation -> risk -> execution)"
        ),
    )
    args = parser.parse_args()

    # Resolve symbol list
    if args.watchlist:
        symbols = WATCHLISTS[args.watchlist]
    elif args.symbols:
        symbols = args.symbols
    else:
        symbols = WATCHLISTS["nse20"]

    # Date range
    if args.from_date and args.to_date:
        from_date, to_date = args.from_date, args.to_date
    else:
        from_date, to_date = _default_date_range()

    run_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    results_csv = REPORTS_DIR / "results.csv"
    trades_csv = REPORTS_DIR / "trades.csv"

    _ensure_csv(results_csv, RESULTS_FIELDS)
    _ensure_csv(trades_csv, TRADES_FIELDS)

    print(
        f"Batch backtest: {len(symbols)} symbols | "
        f"{from_date} -> {to_date} | interval={args.interval}"
        + (f" | ensemble={args.ensemble}" if args.ensemble > 0 else "")
        + (" | live_parity=on" if args.live_parity else "")
        + (" | orchestrator_parity=on" if args.orchestrator_parity else "")
    )
    print(f"Results -> {results_csv}")
    print(f"Trades  -> {trades_csv}")
    print("-" * 60)

    for idx, symbol in enumerate(symbols, 1):
        print(f"[{idx}/{len(symbols)}] {symbol} ...", flush=True)
        _run_symbol(
            symbol=symbol,
            exchange=args.exchange,
            interval=args.interval,
            from_date=from_date,
            to_date=to_date,
            capital=args.capital,
            lot_size=args.lot_size,
            risk_pct=args.risk_pct,
            trailing_atr=args.trailing_atr,
            walk_forward=args.walk_forward,
            run_at=run_at,
            results_csv=results_csv,
            trades_csv=trades_csv,
            use_optimized=args.use_optimized,
            live_parity=args.live_parity,
            orchestrator_parity=args.orchestrator_parity,
            ensemble=args.ensemble,
            min_confidence=args.min_confidence,
        )

    print("-" * 60)
    print(f"Done. Results saved to {results_csv} and {trades_csv}")


if __name__ == "__main__":
    _main()
