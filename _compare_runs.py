"""Quick side-by-side comparison of two backtest runs (baseline vs optimized).

Auto-picks the last two runs from results.csv, or accepts explicit timestamps.
Shows per-symbol delta, per-strategy delta, trade count changes, and Optuna
param summary.

Usage::

    python _compare_runs.py
    python _compare_runs.py --baseline "2026-04-23 16:07:33" --optimized "2026-04-23 17:29:34"
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path

import yaml


def _load_csv(path: str) -> list[dict]:
    """Read a CSV file into a list of dicts."""
    with open(path) as fh:
        return list(csv.DictReader(fh))


def _pct(delta: float, base: float) -> float:
    """Percentage change, safe against zero denominator."""
    return (delta / abs(base) * 100) if base != 0 else 0.0


def _load_optuna_params(symbol: str) -> dict:
    """Load per-symbol optimized params YAML."""
    path = Path("config") / f"params_{symbol.lower()}.yaml"
    if not path.exists():
        return {}
    with path.open() as fh:
        return yaml.safe_load(fh) or {}


def main() -> None:
    """Entry point for the quick run comparison."""
    parser = argparse.ArgumentParser(description="Compare two backtest runs")
    parser.add_argument("--baseline", default=None, help="Baseline run_at timestamp")
    parser.add_argument("--optimized", default=None, help="Optimized run_at timestamp")
    args = parser.parse_args()

    rows = _load_csv("backtest/reports/results.csv")
    runs = sorted(set(r["run_at"] for r in rows))

    if args.baseline and args.optimized:
        base_run, opt_run = args.baseline, args.optimized
    elif len(runs) >= 2:
        base_run, opt_run = runs[-2], runs[-1]
    else:
        raise SystemExit(f"Need at least 2 runs, found {len(runs)}: {runs}")

    base = [r for r in rows if r["run_at"] == base_run]
    opt = [r for r in rows if r["run_at"] == opt_run]

    W = 100

    print("=" * W)
    print(f"  BASELINE:  {base_run}")
    print(f"  OPTIMIZED: {opt_run}")
    print("=" * W)

    # -- Per-symbol aggregated comparison ---------------------------------
    base_by_sym: dict[str, float] = {}
    opt_by_sym: dict[str, float] = {}
    base_tr_sym: dict[str, int] = {}
    opt_tr_sym: dict[str, int] = {}
    base_wr_sym: dict[str, list] = {}
    opt_wr_sym: dict[str, list] = {}

    for r in base:
        s = r["symbol"]
        base_by_sym[s] = base_by_sym.get(s, 0) + float(r["total_pnl"])
        base_tr_sym[s] = base_tr_sym.get(s, 0) + int(r["trades"])
        base_wr_sym.setdefault(s, []).append((float(r["win_rate"]), int(r["trades"])))
    for r in opt:
        s = r["symbol"]
        opt_by_sym[s] = opt_by_sym.get(s, 0) + float(r["total_pnl"])
        opt_tr_sym[s] = opt_tr_sym.get(s, 0) + int(r["trades"])
        opt_wr_sym.setdefault(s, []).append((float(r["win_rate"]), int(r["trades"])))

    def _avg_wr(wr_list: list[tuple[float, int]]) -> float:
        """Weighted average win rate."""
        total = sum(t for _, t in wr_list)
        if total == 0:
            return 0.0
        return sum(w * t for w, t in wr_list) / total

    print(f"\n  PER-SYMBOL SUMMARY")
    print(f"  {'-' * (W - 4)}")
    hdr = (
        f"  {'Symbol':<14} {'Base PnL':>11} {'Opt PnL':>11} {'Delta':>11} "
        f"{'Improv':>8} {'B.Trd':>7} {'O.Trd':>7} {'B.WR':>7} {'O.WR':>7} {'Params':>6}"
    )
    print(hdr)
    print(f"  {'-' * (W - 4)}")

    total_base = total_opt = 0
    improved = 0
    all_symbols = sorted(set(list(base_by_sym.keys()) + list(opt_by_sym.keys())))

    for s in all_symbols:
        b = base_by_sym.get(s, 0)
        o = opt_by_sym.get(s, 0)
        d = o - b
        total_base += b
        total_opt += o
        pct = _pct(d, b)
        bt = base_tr_sym.get(s, 0)
        ot = opt_tr_sym.get(s, 0)
        bw = _avg_wr(base_wr_sym.get(s, []))
        ow = _avg_wr(opt_wr_sym.get(s, []))
        has_params = "Y" if Path(f"config/params_{s.lower()}.yaml").exists() else "-"
        tag = "+" if d > 0 else "-" if d < 0 else "="
        if d > 0:
            improved += 1
        print(
            f"  {s:<14} {b:>11,.2f} {o:>11,.2f} {d:>+11,.2f} "
            f"{pct:>+7.1f}% {bt:>7,} {ot:>7,} {bw:>7.1%} {ow:>7.1%} {has_params:>6} {tag}"
        )

    delta = total_opt - total_base
    pct = _pct(delta, total_base)
    print(f"  {'-' * (W - 4)}")
    print(
        f"  {'TOTAL':<14} {total_base:>11,.2f} {total_opt:>11,.2f} "
        f"{delta:>+11,.2f} {pct:>+7.1f}%"
    )
    print(f"  Improved: {improved}/{len(all_symbols)} symbols")

    # -- Per-strategy aggregated comparison --------------------------------
    base_by_strat: dict[str, float] = {}
    opt_by_strat: dict[str, float] = {}
    base_tr_strat: dict[str, int] = {}
    opt_tr_strat: dict[str, int] = {}

    for r in base:
        st = r["strategy"]
        base_by_strat[st] = base_by_strat.get(st, 0) + float(r["total_pnl"])
        base_tr_strat[st] = base_tr_strat.get(st, 0) + int(r["trades"])
    for r in opt:
        st = r["strategy"]
        opt_by_strat[st] = opt_by_strat.get(st, 0) + float(r["total_pnl"])
        opt_tr_strat[st] = opt_tr_strat.get(st, 0) + int(r["trades"])

    print(f"\n  PER-STRATEGY SUMMARY")
    print(f"  {'-' * (W - 4)}")
    print(
        f"  {'Strategy':<22} {'Base PnL':>12} {'Opt PnL':>12} {'Delta':>12} "
        f"{'B.Trd':>8} {'O.Trd':>8}"
    )
    print(f"  {'-' * 70}")

    all_strats = sorted(set(list(base_by_strat.keys()) + list(opt_by_strat.keys())))
    for st in all_strats:
        b = base_by_strat.get(st, 0)
        o = opt_by_strat.get(st, 0)
        d = o - b
        bt = base_tr_strat.get(st, 0)
        ot = opt_tr_strat.get(st, 0)
        tag = " <--" if abs(d) > 5000 else ""
        ens_tag = " (ENSEMBLE)" if st.startswith("ensemble_") else ""
        print(
            f"  {st:<22} {b:>12,.2f} {o:>12,.2f} {d:>+12,.2f} "
            f"{bt:>8,} {ot:>8,}{tag}{ens_tag}"
        )

    bt = sum(int(r["trades"]) for r in base)
    ot = sum(int(r["trades"]) for r in opt)
    print(f"\n  Total trades: {bt:,} -> {ot:,} ({ot - bt:+,})")

    # -- Optuna best-value summary per symbol ------------------------------
    print(f"\n  OPTUNA BEST VALUES (from config/params_*.yaml)")
    print(f"  {'-' * (W - 4)}")
    for sym in all_symbols:
        data = _load_optuna_params(sym)
        if not data:
            continue
        strats = sorted(data.keys())
        vals = []
        for s in strats:
            bv = data[s].get("best_value", 0)
            metric = data[s].get("metric", "sortino")
            vals.append(f"{s}({metric}={bv:.1f})")
        print(f"  {sym:<14} {', '.join(vals)}")

    print()


if __name__ == "__main__":
    main()
