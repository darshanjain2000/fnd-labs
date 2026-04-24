"""Detailed strategy × symbol comparison across backtest runs.

Compares the last two distinct runs in results.csv (auto-detects baseline vs
optimized). Shows per-strategy breakdown, per-symbol delta, optimized params
with their Optuna best-values, and a trade-level analysis from trades.csv.

Usage::

    python _detailed_compare.py
    python _detailed_compare.py --baseline "2026-04-23 16:07:33" --optimized "2026-04-23 17:29:34"
"""
from __future__ import annotations

import argparse
import csv
import os
from collections import defaultdict
from pathlib import Path

import yaml


# ── Helpers ──────────────────────────────────────────────────────────────────


def _load_csv(path: str) -> list[dict]:
    """Read a CSV file into a list of dicts."""
    with open(path) as fh:
        return list(csv.DictReader(fh))


def _pct(delta: float, base: float) -> float:
    """Percentage change, safe against zero denominator."""
    return (delta / abs(base) * 100) if base != 0 else 0.0


def _load_optuna_params(symbol: str) -> dict:
    """Load per-symbol optimized params YAML (strategy → params + best_value)."""
    path = Path("config") / f"params_{symbol.lower()}.yaml"
    if not path.exists():
        return {}
    with path.open() as fh:
        return yaml.safe_load(fh) or {}


def _weighted_wr(rows: list[dict]) -> float:
    """Trade-weighted average win rate from results rows."""
    total_trades = sum(int(r["trades"]) for r in rows)
    if total_trades == 0:
        return 0.0
    return sum(float(r["win_rate"]) * int(r["trades"]) for r in rows) / total_trades


def _pick_runs(rows: list[dict], baseline: str | None, optimized: str | None) -> tuple[str, str]:
    """Resolve which two run_at timestamps to compare."""
    runs = sorted(set(r["run_at"] for r in rows))
    if baseline and optimized:
        return baseline, optimized
    if len(runs) < 2:
        raise SystemExit(f"Need at least 2 runs in results.csv, found {len(runs)}")
    return runs[-2], runs[-1]


# ── Trade-level analysis ────────────────────────────────────────────────────


def _analyse_trades(
    trades: list[dict], run_at: str
) -> dict[tuple[str, str], dict]:
    """Build per (symbol, strategy) trade stats from trades.csv for a run."""
    filtered = [t for t in trades if t["run_at"] == run_at]
    stats: dict[tuple[str, str], dict] = {}
    for t in filtered:
        key = (t["symbol"], t["strategy"])
        if key not in stats:
            stats[key] = {"wins": 0, "losses": 0, "total_pnl": 0.0, "avg_bars": 0, "count": 0}
        s = stats[key]
        pnl = float(t["pnl"])
        s["count"] += 1
        s["total_pnl"] += pnl
        s["avg_bars"] += int(t["bars_held"])
        if pnl > 0:
            s["wins"] += 1
        else:
            s["losses"] += 1
    for s in stats.values():
        s["avg_bars"] = round(s["avg_bars"] / max(s["count"], 1), 1)
    return stats


# ── Main ─────────────────────────────────────────────────────────────────────


def main() -> None:
    """Entry point for the detailed comparison report."""
    parser = argparse.ArgumentParser(description="Detailed backtest comparison")
    parser.add_argument("--baseline", default=None, help="Baseline run_at timestamp")
    parser.add_argument("--optimized", default=None, help="Optimized run_at timestamp")
    args = parser.parse_args()

    rows = _load_csv("backtest/reports/results.csv")
    trades = _load_csv("backtest/reports/trades.csv")
    base_run, opt_run = _pick_runs(rows, args.baseline, args.optimized)

    base = [r for r in rows if r["run_at"] == base_run]
    opt = [r for r in rows if r["run_at"] == opt_run]

    strategies = sorted(set(r["strategy"] for r in base + opt))
    symbols = sorted(set(r["symbol"] for r in base + opt))

    base_idx = {(r["symbol"], r["strategy"]): r for r in base}
    opt_idx = {(r["symbol"], r["strategy"]): r for r in opt}

    base_trades = _analyse_trades(trades, base_run)
    opt_trades = _analyse_trades(trades, opt_run)

    W = 120

    # ── Header ───────────────────────────────────────────────────────────
    print("=" * W)
    print(f"  DETAILED STRATEGY × SYMBOL COMPARISON")
    print(f"  Baseline:  {base_run}")
    print(f"  Optimized: {opt_run}")
    print(f"  Symbols: {len(symbols)}  |  Strategies: {len(strategies)}")
    print("=" * W)

    # ── Per-strategy detail ──────────────────────────────────────────────
    for strat in strategies:
        if strat.startswith("ensemble_"):
            continue  # ensemble handled separately

        b_rows = [r for r in base if r["strategy"] == strat]
        o_rows = [r for r in opt if r["strategy"] == strat]

        b_pnl = sum(float(r["total_pnl"]) for r in b_rows)
        o_pnl = sum(float(r["total_pnl"]) for r in o_rows)
        b_trades = sum(int(r["trades"]) for r in b_rows)
        o_trades = sum(int(r["trades"]) for r in o_rows)
        b_wr = _weighted_wr(b_rows)
        o_wr = _weighted_wr(o_rows)

        delta = o_pnl - b_pnl
        pct = _pct(delta, b_pnl)
        if o_pnl > 0:
            tag = "PROFITABLE"
        elif delta > 0:
            tag = "improved"
        else:
            tag = "WORSE"

        print(f"\n{'─' * W}")
        print(f"  {strat.upper()}")
        print(
            f"  PnL:       {b_pnl:>12,.2f}  ->  {o_pnl:>12,.2f}  "
            f"({delta:>+12,.2f}, {pct:>+.1f}%)  [{tag}]"
        )
        print(
            f"  Trades:    {b_trades:>6,}     ->  {o_trades:>6,}     "
            f"({o_trades - b_trades:>+6,})"
        )
        print(
            f"  Win Rate:  {b_wr:>6.1%}     ->  {o_wr:>6.1%}     "
            f"({o_wr - b_wr:>+.1%})"
        )
        print(f"{'─' * W}")

        hdr = (
            f"  {'Symbol':<14} {'B.PnL':>10} {'O.PnL':>10} {'Delta':>10} "
            f"{'B.Trd':>6} {'O.Trd':>6} {'B.WR':>7} {'O.WR':>7} "
            f"{'B.Sharpe':>9} {'O.Sharpe':>9} {'AvgBars':>8}"
        )
        print(hdr)
        print(f"  {'-' * (W - 4)}")

        prof_b = prof_o = 0
        for sym in symbols:
            br = base_idx.get((sym, strat))
            orr = opt_idx.get((sym, strat))
            if not br and not orr:
                continue
            bp = float(br["total_pnl"]) if br else 0
            op = float(orr["total_pnl"]) if orr else 0
            bt = int(br["trades"]) if br else 0
            ot = int(orr["trades"]) if orr else 0
            bw = float(br["win_rate"]) if br else 0
            ow = float(orr["win_rate"]) if orr else 0
            bs = float(br["sharpe"]) if br else 0
            os_ = float(orr["sharpe"]) if orr else 0
            d = op - bp
            if bp > 0:
                prof_b += 1
            if op > 0:
                prof_o += 1
            avg_bars = opt_trades.get((sym, strat), {}).get("avg_bars", "-")
            marker = " **" if op > 0 and bp <= 0 else " !!" if op < bp else ""
            print(
                f"  {sym:<14} {bp:>10,.2f} {op:>10,.2f} {d:>+10,.2f} "
                f"{bt:>6} {ot:>6} {bw:>7.1%} {ow:>7.1%} "
                f"{bs:>9.2f} {os_:>9.2f} {str(avg_bars):>8}{marker}"
            )

        print(f"  Profitable symbols: {prof_b} -> {prof_o}")

    # ── Grand summary ────────────────────────────────────────────────────
    print(f"\n{'=' * W}")
    print("  GRAND SUMMARY BY STRATEGY")
    print(f"{'=' * W}")
    hdr = (
        f"  {'Strategy':<22} {'Base PnL':>12} {'Opt PnL':>12} {'Delta':>12} "
        f"{'B.Trd':>8} {'O.Trd':>8} {'B.WR':>7} {'O.WR':>7} "
        f"{'B.Sort':>8} {'O.Sort':>8} {'Status':>12}"
    )
    print(hdr)
    print(f"  {'-' * (W - 4)}")

    grand_b = grand_o = 0
    for strat in strategies:
        b_rows = [r for r in base if r["strategy"] == strat]
        o_rows = [r for r in opt if r["strategy"] == strat]
        bp = sum(float(r["total_pnl"]) for r in b_rows)
        op = sum(float(r["total_pnl"]) for r in o_rows)
        bt = sum(int(r["trades"]) for r in b_rows)
        ot = sum(int(r["trades"]) for r in o_rows)
        bw = _weighted_wr(b_rows)
        ow = _weighted_wr(o_rows)
        b_sort = (
            sum(float(r["sortino"]) for r in b_rows) / max(len(b_rows), 1) if b_rows else 0
        )
        o_sort = (
            sum(float(r["sortino"]) for r in o_rows) / max(len(o_rows), 1) if o_rows else 0
        )
        d = op - bp
        grand_b += bp
        grand_o += op
        status = "PROFITABLE" if op > 0 else "improved" if d > 0 else "WORSE"
        print(
            f"  {strat:<22} {bp:>12,.2f} {op:>12,.2f} {d:>+12,.2f} "
            f"{bt:>8,} {ot:>8,} {bw:>7.1%} {ow:>7.1%} "
            f"{b_sort:>8.2f} {o_sort:>8.2f} {status:>12}"
        )

    d = grand_o - grand_b
    pct = _pct(d, grand_b)
    print(f"  {'-' * (W - 4)}")
    print(f"  {'TOTAL':<22} {grand_b:>12,.2f} {grand_o:>12,.2f} {d:>+12,.2f}  ({pct:>+.1f}%)")

    # ── Top 10 best / worst movers ───────────────────────────────────────
    all_pairs = []
    for sym in symbols:
        for strat in strategies:
            br = base_idx.get((sym, strat))
            orr = opt_idx.get((sym, strat))
            if br and orr:
                bp = float(br["total_pnl"])
                op = float(orr["total_pnl"])
                all_pairs.append((sym, strat, bp, op, op - bp))

    all_pairs.sort(key=lambda x: x[4], reverse=True)

    print(f"\n{'=' * W}")
    print("  TOP 10 BEST IMPROVEMENTS (strategy x symbol)")
    print(f"{'=' * W}")
    print(f"  {'Symbol':<14} {'Strategy':<22} {'Base PnL':>10} {'Opt PnL':>10} {'Delta':>10}")
    print(f"  {'-' * 70}")
    for sym, strat, bp, op, d in all_pairs[:10]:
        tag = " FLIPPED!" if op > 0 and bp < 0 else ""
        print(f"  {sym:<14} {strat:<22} {bp:>10,.2f} {op:>10,.2f} {d:>+10,.2f}{tag}")

    print(f"\n  WORST 5 REGRESSIONS")
    print(f"  {'-' * 70}")
    for sym, strat, bp, op, d in all_pairs[-5:]:
        print(f"  {sym:<14} {strat:<22} {bp:>10,.2f} {op:>10,.2f} {d:>+10,.2f}")

    # ── Optuna params per symbol ─────────────────────────────────────────
    print(f"\n{'=' * W}")
    print("  OPTIMIZED PARAMS PER SYMBOL (from config/params_*.yaml)")
    print(f"{'=' * W}")
    for sym in symbols:
        data = _load_optuna_params(sym)
        if not data:
            print(f"  {sym:<14} NO PARAMS FILE")
            continue
        print(f"\n  {sym}")
        for strat_name in sorted(data.keys()):
            entry = data[strat_name]
            best_val = entry.get("best_value", "?")
            metric = entry.get("metric", "sortino")
            params = entry.get("best_params", {})
            param_str = ", ".join(f"{k}={v:.3f}" if isinstance(v, float) else f"{k}={v}" for k, v in sorted(params.items()))
            print(f"    {strat_name:<22} {metric}={best_val:<10.4f}  {param_str}")

    # ── Ensemble strategy pair frequency (from trades.csv) ───────────────
    ens_trades = [
        t for t in trades
        if t["run_at"] == opt_run and t.get("strategy", "").startswith("ensemble_")
    ]
    if ens_trades:
        # Check for contributing_strategies field (new format) or fallback
        pair_counts: dict[str, int] = defaultdict(int)
        pair_pnl: dict[str, float] = defaultdict(float)
        for t in ens_trades:
            contribs = t.get("contributing_strategies", "")
            if not contribs:
                # Fallback: check for extra field from old CSV format
                contribs = t.get(None, "")
                if isinstance(contribs, list):
                    contribs = contribs[0] if contribs else ""
            if contribs:
                pair_counts[contribs] += 1
                pair_pnl[contribs] += float(t["pnl"])

        if pair_counts:
            print(f"\n{'=' * W}")
            print("  ENSEMBLE CONTRIBUTING STRATEGY COMBINATIONS")
            print(f"{'=' * W}")
            print(f"  {'Strategies':<55} {'Trades':>8} {'Total PnL':>12} {'Avg PnL':>10}")
            print(f"  {'-' * 90}")
            for combo in sorted(pair_counts, key=lambda c: pair_pnl[c], reverse=True):
                cnt = pair_counts[combo]
                pnl = pair_pnl[combo]
                avg = pnl / cnt
                tag = " ++" if pnl > 0 else ""
                print(f"  {combo:<55} {cnt:>8} {pnl:>12,.2f} {avg:>10,.2f}{tag}")

    print()


if __name__ == "__main__":
    main()
"""Detailed strategy-wise comparison: baseline vs optimized."""
import csv
from collections import defaultdict

rows = list(csv.DictReader(open("backtest/reports/results.csv")))
runs = sorted(set(r["run_at"] for r in rows))
base_run, opt_run = runs[0], runs[2]

base = [r for r in rows if r["run_at"] == base_run]
opt = [r for r in rows if r["run_at"] == opt_run]

strategies = sorted(set(r["strategy"] for r in base))
symbols = sorted(set(r["symbol"] for r in base))

# Index: (symbol, strategy) -> row
base_idx = {(r["symbol"], r["strategy"]): r for r in base}
opt_idx = {(r["symbol"], r["strategy"]): r for r in opt}

print("=" * 100)
print(f"  DETAILED STRATEGY-WISE COMPARISON")
print(f"  Baseline: {base_run}  |  Optimized: {opt_run}")
print(f"  Symbols: {len(symbols)}  |  Strategies: {len(strategies)}")
print("=" * 100)

# ── Per-strategy detail ──────────────────────────────────────────────
for strat in strategies:
    b_rows = [r for r in base if r["strategy"] == strat]
    o_rows = [r for r in opt if r["strategy"] == strat]

    b_pnl = sum(float(r["total_pnl"]) for r in b_rows)
    o_pnl = sum(float(r["total_pnl"]) for r in o_rows)
    b_trades = sum(int(r["trades"]) for r in b_rows)
    o_trades = sum(int(r["trades"]) for r in o_rows)
    b_wr = sum(float(r["win_rate"]) * int(r["trades"]) for r in b_rows) / max(b_trades, 1)
    o_wr = sum(float(r["win_rate"]) * int(r["trades"]) for r in o_rows) / max(o_trades, 1)

    delta = o_pnl - b_pnl
    pct = (delta / abs(b_pnl) * 100) if b_pnl != 0 else 0
    tag = "PROFITABLE!" if o_pnl > 0 else "improved" if delta > 0 else "WORSE"

    print(f"\n{'─' * 100}")
    print(f"  {strat.upper()}")
    print(f"  Total PnL:  {b_pnl:>12,.2f} -> {o_pnl:>12,.2f}  ({delta:>+12,.2f}, {pct:>+.1f}%)  [{tag}]")
    print(f"  Trades:     {b_trades:>6,} -> {o_trades:>6,}  ({o_trades - b_trades:>+6,})")
    print(f"  Avg WinRate: {b_wr:>6.1%} -> {o_wr:>6.1%}  ({o_wr - b_wr:>+.1%})")
    print(f"{'─' * 100}")

    hdr = f"  {'Symbol':<15} {'B.PnL':>10} {'O.PnL':>10} {'Delta':>10} {'B.Trd':>6} {'O.Trd':>6} {'B.WR':>7} {'O.WR':>7} {'B.Sharpe':>9} {'O.Sharpe':>9}"
    print(hdr)
    print(f"  {'-' * 95}")

    profitable_base = 0
    profitable_opt = 0
    for sym in symbols:
        br = base_idx.get((sym, strat))
        orr = opt_idx.get((sym, strat))
        if not br:
            continue
        bp = float(br["total_pnl"])
        op = float(orr["total_pnl"]) if orr else 0
        bt = int(br["trades"])
        ot = int(orr["trades"]) if orr else 0
        bw = float(br["win_rate"])
        ow = float(orr["win_rate"]) if orr else 0
        bs = float(br["sharpe"])
        os_ = float(orr["sharpe"]) if orr else 0
        d = op - bp
        if bp > 0:
            profitable_base += 1
        if op > 0:
            profitable_opt += 1
        marker = " **" if op > 0 and bp <= 0 else " !!" if op < bp else ""
        print(f"  {sym:<15} {bp:>10,.2f} {op:>10,.2f} {d:>+10,.2f} {bt:>6} {ot:>6} {bw:>7.1%} {ow:>7.1%} {bs:>9.2f} {os_:>9.2f}{marker}")

    print(f"  Profitable symbols: {profitable_base} -> {profitable_opt}")

# ── Grand summary ────────────────────────────────────────────────────
print(f"\n{'=' * 100}")
print("  GRAND SUMMARY BY STRATEGY")
print(f"{'=' * 100}")
print(f"  {'Strategy':<22} {'Base PnL':>12} {'Opt PnL':>12} {'Delta':>12} {'B.Trades':>9} {'O.Trades':>9} {'B.WR':>7} {'O.WR':>7} {'Status':>12}")
print(f"  {'-' * 97}")

grand_b = grand_o = 0
for strat in strategies:
    b_rows = [r for r in base if r["strategy"] == strat]
    o_rows = [r for r in opt if r["strategy"] == strat]
    bp = sum(float(r["total_pnl"]) for r in b_rows)
    op = sum(float(r["total_pnl"]) for r in o_rows)
    bt = sum(int(r["trades"]) for r in b_rows)
    ot = sum(int(r["trades"]) for r in o_rows)
    bw = sum(float(r["win_rate"]) * int(r["trades"]) for r in b_rows) / max(bt, 1)
    ow = sum(float(r["win_rate"]) * int(r["trades"]) for r in o_rows) / max(ot, 1)
    d = op - bp
    grand_b += bp
    grand_o += op
    status = "PROFITABLE" if op > 0 else "improved" if d > 0 else "WORSE"
    print(f"  {strat:<22} {bp:>12,.2f} {op:>12,.2f} {d:>+12,.2f} {bt:>9,} {ot:>9,} {bw:>7.1%} {ow:>7.1%} {status:>12}")

d = grand_o - grand_b
print(f"  {'-' * 97}")
print(f"  {'TOTAL':<22} {grand_b:>12,.2f} {grand_o:>12,.2f} {d:>+12,.2f}")

# ── Top / bottom movers ─────────────────────────────────────────────
print(f"\n{'=' * 100}")
print("  TOP 10 BEST INDIVIDUAL IMPROVEMENTS (strategy x symbol)")
print(f"{'=' * 100}")
all_pairs = []
for sym in symbols:
    for strat in strategies:
        br = base_idx.get((sym, strat))
        orr = opt_idx.get((sym, strat))
        if br and orr:
            bp = float(br["total_pnl"])
            op = float(orr["total_pnl"])
            all_pairs.append((sym, strat, bp, op, op - bp))

all_pairs.sort(key=lambda x: x[4], reverse=True)
print(f"  {'Symbol':<15} {'Strategy':<22} {'Base PnL':>10} {'Opt PnL':>10} {'Delta':>10}")
print(f"  {'-' * 70}")
for sym, strat, bp, op, d in all_pairs[:10]:
    tag = " FLIPPED" if op > 0 and bp < 0 else ""
    print(f"  {sym:<15} {strat:<22} {bp:>10,.2f} {op:>10,.2f} {d:>+10,.2f}{tag}")

print(f"\n  TOP 5 WORST REGRESSIONS")
print(f"  {'-' * 70}")
for sym, strat, bp, op, d in all_pairs[-5:]:
    print(f"  {sym:<15} {strat:<22} {bp:>10,.2f} {op:>10,.2f} {d:>+10,.2f}")

# ── Params loaded per symbol ─────────────────────────────────────────
import yaml, os
print(f"\n{'=' * 100}")
print("  OPTIMIZED PARAMS LOADED PER SYMBOL")
print(f"{'=' * 100}")
for sym in symbols:
    ypath = f"config/params_{sym.lower()}.yaml"
    if os.path.exists(ypath):
        with open(ypath) as f:
            data = yaml.safe_load(f)
        strats = sorted(data.keys())
        vals = {s: f"{data[s]['best_value']:.1f}" for s in strats}
        print(f"  {sym:<15} {len(strats)} strats: {', '.join(f'{s}({vals[s]})' for s in strats)}")
    else:
        print(f"  {sym:<15} NO PARAMS FILE")
