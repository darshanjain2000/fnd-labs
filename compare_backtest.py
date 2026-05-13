"""Compare baseline vs optimized backtest results from results.csv.

Reads ``backtest/reports/results.csv`` and groups rows by run_at timestamp.
The LATEST two distinct run_at timestamps are compared as baseline and optimized.

Usage::

    python compare_backtest.py
    python compare_backtest.py --baseline "2026-04-22 22:45:00" --optimized "2026-04-22 23:30:00"
"""
from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path


RESULTS_CSV = Path(__file__).parent / "backtest" / "reports" / "results.csv"


def _load_results() -> list[dict]:
    """Load all rows from results.csv, excluding old synthetic-data NIFTY/SENSEX runs.

    Returns:
        List of result row dicts.
    """
    rows = list(csv.DictReader(RESULTS_CSV.open()))
    return [r for r in rows if r["symbol"] not in ("NIFTY", "SENSEX", "BACKTEST")]


def _group_by_run(rows: list[dict]) -> dict[str, list[dict]]:
    """Group result rows by run_at timestamp.

    Args:
        rows: All result rows.

    Returns:
        Mapping of run_at string to list of rows.
    """
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        groups[r["run_at"]].append(r)
    return groups


def _summarise(rows: list[dict]) -> dict:
    """Aggregate metrics for a set of result rows.

    Args:
        rows: Result rows belonging to one run.

    Returns:
        Summary dict with totals and per-strategy/per-symbol breakdowns.
    """
    total_trades = sum(int(r["trades"]) for r in rows)
    total_pnl = sum(float(r["total_pnl"]) for r in rows)
    profitable = sum(1 for r in rows if float(r["total_pnl"]) > 0)
    symbols = sorted(set(r["symbol"] for r in rows))

    strat_pnl: dict[str, float] = defaultdict(float)
    strat_trades: dict[str, int] = defaultdict(int)
    sym_pnl: dict[str, float] = defaultdict(float)
    for r in rows:
        strat_pnl[r["strategy"]] += float(r["total_pnl"])
        strat_trades[r["strategy"]] += int(r["trades"])
        sym_pnl[r["symbol"]] += float(r["total_pnl"])

    return {
        "symbols": symbols,
        "total_trades": total_trades,
        "total_pnl": total_pnl,
        "profitable_runs": profitable,
        "total_runs": len(rows),
        "strat_pnl": dict(strat_pnl),
        "strat_trades": dict(strat_trades),
        "sym_pnl": dict(sym_pnl),
    }


def _print_comparison(label_a: str, a: dict, label_b: str, b: dict) -> None:
    """Print a side-by-side comparison of two backtest summaries.

    Args:
        label_a: Label for the first run (baseline).
        a: Summary dict for the first run.
        label_b: Label for the second run (optimized).
        b: Summary dict for the second run.
    """
    delta_pnl = b["total_pnl"] - a["total_pnl"]
    delta_trades = b["total_trades"] - a["total_trades"]
    delta_prof = b["profitable_runs"] - a["profitable_runs"]

    print("=" * 70)
    print(f"  BASELINE  ({label_a})")
    print(f"  OPTIMIZED ({label_b})")
    print("=" * 70)
    print(f"{'Metric':<30} {'Baseline':>15} {'Optimized':>15} {'Delta':>10}")
    print("-" * 70)
    print(f"{'Total trades':<30} {a['total_trades']:>15,} {b['total_trades']:>15,} {delta_trades:>+10,}")
    print(f"{'Total net PnL':<30} {a['total_pnl']:>15,.2f} {b['total_pnl']:>15,.2f} {delta_pnl:>+10,.2f}")
    print(
        f"{'Profitable strategy/sym runs':<30} "
        f"{a['profitable_runs']:>15}/{a['total_runs']} "
        f"{b['profitable_runs']:>15}/{b['total_runs']} "
        f"{delta_prof:>+10}"
    )
    print()

    # Strategy-level delta
    print(f"{'Strategy':<22} {'Base PnL':>12} {'Opt PnL':>12} {'Delta':>10} {'Base Trades':>12} {'Opt Trades':>12}")
    print("-" * 82)
    all_strats = sorted(set(list(a["strat_pnl"].keys()) + list(b["strat_pnl"].keys())))
    for s in all_strats:
        ap = a["strat_pnl"].get(s, 0.0)
        bp = b["strat_pnl"].get(s, 0.0)
        at = a["strat_trades"].get(s, 0)
        bt = b["strat_trades"].get(s, 0)
        mark = " <--" if bp > ap else ""
        print(f"{s:<22} {ap:>12,.2f} {bp:>12,.2f} {bp - ap:>+10,.2f} {at:>12,} {bt:>12,}{mark}")

    print()
    print(f"{'Symbol':<15} {'Base PnL':>12} {'Opt PnL':>12} {'Delta':>10}")
    print("-" * 52)
    all_syms = sorted(set(list(a["sym_pnl"].keys()) + list(b["sym_pnl"].keys())))
    for sym in all_syms:
        ap = a["sym_pnl"].get(sym, 0.0)
        bp = b["sym_pnl"].get(sym, 0.0)
        mark = " +" if bp > ap else ""
        print(f"{sym:<15} {ap:>12,.2f} {bp:>12,.2f} {bp - ap:>+10,.2f}{mark}")


def _main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Compare baseline vs optimized backtest results.")
    parser.add_argument("--baseline", default=None, help="run_at timestamp of the baseline run")
    parser.add_argument("--optimized", default=None, help="run_at timestamp of the optimized run")
    args = parser.parse_args()

    rows = _load_results()
    groups = _group_by_run(rows)
    run_timestamps = sorted(groups.keys())

    if len(run_timestamps) < 2:
        print("Need at least 2 distinct runs in results.csv to compare.")
        print(f"Found: {run_timestamps}")
        return

    label_a = args.baseline or run_timestamps[-2]
    label_b = args.optimized or run_timestamps[-1]

    if label_a not in groups:
        print(f"run_at '{label_a}' not found. Available: {run_timestamps}")
        return
    if label_b not in groups:
        print(f"run_at '{label_b}' not found. Available: {run_timestamps}")
        return

    a = _summarise(groups[label_a])
    b = _summarise(groups[label_b])

    _print_comparison(label_a, a, label_b, b)


if __name__ == "__main__":
    _main()
