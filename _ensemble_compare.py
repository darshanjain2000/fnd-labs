"""Ensemble vs individual strategy comparison from backtest results.

Shows ensemble P&L vs each individual strategy per symbol, trade-level
contribution analysis, and strategy-pair win-rate breakdown.

Usage::

    python _ensemble_compare.py
    python _ensemble_compare.py --run "2026-04-23 17:29:34"
"""
from __future__ import annotations

import argparse
import csv
from collections import defaultdict


def _load_csv(path: str) -> list[dict]:
    """Read a CSV file into a list of dicts."""
    with open(path) as fh:
        return list(csv.DictReader(fh))


def _weighted_wr(rows: list[dict]) -> float:
    """Trade-weighted average win rate."""
    total = sum(int(r["trades"]) for r in rows)
    if total == 0:
        return 0.0
    return sum(float(r["win_rate"]) * int(r["trades"]) for r in rows) / total


def main() -> None:
    """Entry point for ensemble comparison."""
    parser = argparse.ArgumentParser(description="Ensemble vs individual comparison")
    parser.add_argument("--run", default=None, help="Specific run_at timestamp (default: latest)")
    args = parser.parse_args()

    rows = _load_csv("backtest/reports/results.csv")
    trades_all = _load_csv("backtest/reports/trades.csv")

    runs = sorted(set(r["run_at"] for r in rows))
    run_at = args.run if args.run else runs[-1]
    data = [r for r in rows if r["run_at"] == run_at]

    strategies = sorted(set(r["strategy"] for r in data))
    symbols = sorted(set(r["symbol"] for r in data))
    has_ensemble = any(r["strategy"].startswith("ensemble_") for r in data)
    ens_name = next((s for s in strategies if s.startswith("ensemble_")), "ensemble_2")

    idx = {(r["symbol"], r["strategy"]): r for r in data}

    W = 120

    print("=" * W)
    print(f"  BACKTEST COMPARISON -- Run: {run_at}")
    print(f"  Symbols: {len(symbols)}  |  Strategies: {len(strategies)}")
    print(f"  Ensemble: {'YES (' + ens_name + ')' if has_ensemble else 'NO'}")
    print("=" * W)

    # -- Section 1: Ensemble vs best individual per symbol ----------------
    if has_ensemble:
        print(f"\n{'=' * W}")
        print(f"  {ens_name.upper()} vs BEST INDIVIDUAL STRATEGY (per symbol)")
        print(f"{'=' * W}")
        hdr = (
            f"  {'Symbol':<14} {'Ens.PnL':>10} {'Ens.Trd':>8} {'Ens.WR':>7} {'Ens.Sort':>9} "
            f"{'Best PnL':>10} {'Best Strategy':>22} {'SumAll':>10} {'AllTrd':>8}"
        )
        print(hdr)
        print(f"  {'-' * (W - 4)}")

        ens_total_pnl = 0
        ens_total_trades = 0
        best_total_pnl = 0
        sum_all_pnl = 0
        ens_profitable = 0
        ens_wins_gt50 = 0

        for sym in symbols:
            ens = idx.get((sym, ens_name))
            indiv = [
                (s, idx[(sym, s)])
                for s in strategies
                if not s.startswith("ensemble_") and (sym, s) in idx
            ]

            if ens:
                ep = float(ens["total_pnl"])
                et = int(ens["trades"])
                ew = float(ens["win_rate"])
                es = float(ens["sortino"])
                ens_total_pnl += ep
                ens_total_trades += et
                if ep > 0:
                    ens_profitable += 1
                if ew > 0.5:
                    ens_wins_gt50 += 1
            else:
                ep, et, ew, es = 0, 0, 0, 0

            if indiv:
                best_strat = max(indiv, key=lambda x: float(x[1]["total_pnl"]))
                bp = float(best_strat[1]["total_pnl"])
                bn = best_strat[0]
                sa = sum(float(x[1]["total_pnl"]) for x in indiv)
                at = sum(int(x[1]["trades"]) for x in indiv)
                best_total_pnl += bp
                sum_all_pnl += sa
            else:
                bp, bn, sa, at = 0, "", 0, 0

            tag = " **" if ep > bp and ep > 0 else ""
            print(
                f"  {sym:<14} {ep:>10,.2f} {et:>8} {ew:>7.1%} {es:>9.2f} "
                f"{bp:>10,.2f} {bn:>22} {sa:>10,.2f} {at:>8}{tag}"
            )

        print(f"  {'-' * (W - 4)}")
        print(
            f"  {'TOTAL':<14} {ens_total_pnl:>10,.2f} {ens_total_trades:>8} "
            f"{'':>7} {'':>9} {best_total_pnl:>10,.2f} {'':>22} {sum_all_pnl:>10,.2f}"
        )
        print(f"\n  Ensemble profitable: {ens_profitable}/{len(symbols)} symbols")
        print(f"  Ensemble win rate >50%: {ens_wins_gt50}/{len(symbols)} symbols")
        print(f"  Ensemble avg trades/symbol: {ens_total_trades / max(len(symbols), 1):.1f}")
        print(f"  Ensemble total PnL: {ens_total_pnl:>+,.2f}")
        print(f"  Best-individual total PnL: {best_total_pnl:>+,.2f}")
        print(f"  Sum-all-individual PnL: {sum_all_pnl:>+,.2f}")

    # -- Section 2: Grand summary by strategy -----------------------------
    print(f"\n{'=' * W}")
    print("  GRAND SUMMARY BY STRATEGY")
    print(f"{'=' * W}")
    print(
        f"  {'Strategy':<22} {'Total PnL':>12} {'Trades':>8} {'Avg WR':>8} "
        f"{'Profitable':>11} {'Avg Sharpe':>11} {'Avg Sortino':>12}"
    )
    print(f"  {'-' * (W - 4)}")

    for strat in strategies:
        strat_rows = [r for r in data if r["strategy"] == strat]
        tp = sum(float(r["total_pnl"]) for r in strat_rows)
        tt = sum(int(r["trades"]) for r in strat_rows)
        wr = _weighted_wr(strat_rows)
        prof = sum(1 for r in strat_rows if float(r["total_pnl"]) > 0)
        avg_sh = sum(float(r["sharpe"]) for r in strat_rows) / max(len(strat_rows), 1)
        avg_sort = sum(float(r["sortino"]) for r in strat_rows) / max(len(strat_rows), 1)
        tag = " <-- ENSEMBLE" if strat.startswith("ensemble_") else (" $$" if tp > 0 else "")
        print(
            f"  {strat:<22} {tp:>12,.2f} {tt:>8} {wr:>8.1%} "
            f"{prof:>5}/{len(strat_rows):<5} {avg_sh:>11.2f} {avg_sort:>12.2f}{tag}"
        )

    # -- Section 3: Ensemble ranking by symbol ----------------------------
    if has_ensemble:
        print(f"\n{'=' * W}")
        print("  ENSEMBLE RANKING BY SYMBOL (best to worst)")
        print(f"{'=' * W}")
        ens_pairs = []
        for sym in symbols:
            ens = idx.get((sym, ens_name))
            if ens:
                ens_pairs.append((
                    sym,
                    float(ens["total_pnl"]),
                    int(ens["trades"]),
                    float(ens["win_rate"]),
                    float(ens["sharpe"]),
                    float(ens["sortino"]),
                    float(ens["max_drawdown_pct"]),
                ))

        ens_pairs.sort(key=lambda x: x[1], reverse=True)
        print(
            f"  {'Symbol':<14} {'PnL':>10} {'Trades':>8} {'WinRate':>8} "
            f"{'Sharpe':>8} {'Sortino':>9} {'MaxDD%':>8}"
        )
        print(f"  {'-' * 70}")
        for sym, pnl, trd, wr, sh, sort, dd in ens_pairs:
            tag = " ++" if pnl > 0 else ""
            print(
                f"  {sym:<14} {pnl:>10,.2f} {trd:>8} {wr:>8.1%} "
                f"{sh:>8.2f} {sort:>9.2f} {dd:>8.2%}{tag}"
            )

    # -- Section 4: Ensemble contributing strategy combos -----------------
    ens_trades = [
        t for t in trades_all
        if t["run_at"] == run_at and t.get("strategy", "").startswith("ensemble_")
    ]
    if ens_trades:
        pair_counts: dict[str, int] = defaultdict(int)
        pair_pnl: dict[str, float] = defaultdict(float)
        pair_wins: dict[str, int] = defaultdict(int)

        for t in ens_trades:
            contribs = t.get("contributing_strategies", "")
            if not contribs:
                contribs = t.get(None, "")
                if isinstance(contribs, list):
                    contribs = contribs[0] if contribs else ""
            if contribs:
                pair_counts[contribs] += 1
                pnl = float(t["pnl"])
                pair_pnl[contribs] += pnl
                if pnl > 0:
                    pair_wins[contribs] += 1

        if pair_counts:
            print(f"\n{'=' * W}")
            print("  ENSEMBLE: CONTRIBUTING STRATEGY COMBINATIONS")
            print(f"{'=' * W}")
            print(
                f"  {'Strategy Combination':<55} {'Trades':>7} {'PnL':>11} "
                f"{'Avg PnL':>9} {'WR':>7}"
            )
            print(f"  {'-' * 95}")
            for combo in sorted(pair_counts, key=lambda c: pair_pnl[c], reverse=True):
                cnt = pair_counts[combo]
                pnl = pair_pnl[combo]
                avg = pnl / cnt
                wr = pair_wins[combo] / cnt
                tag = " ++" if pnl > 0 else ""
                print(
                    f"  {combo:<55} {cnt:>7} {pnl:>11,.2f} "
                    f"{avg:>9,.2f} {wr:>7.1%}{tag}"
                )

            # Strategy appearance frequency
            strat_freq: dict[str, int] = defaultdict(int)
            strat_pnl: dict[str, float] = defaultdict(float)
            for combo, cnt in pair_counts.items():
                for s in combo.split(","):
                    strat_freq[s] += cnt
                    strat_pnl[s] += pair_pnl[combo]

            print(f"\n  INDIVIDUAL STRATEGY CONTRIBUTION TO ENSEMBLE")
            print(f"  {'-' * 60}")
            print(f"  {'Strategy':<22} {'Appearances':>12} {'Assoc. PnL':>12}")
            print(f"  {'-' * 50}")
            for s in sorted(strat_freq, key=lambda x: strat_freq[x], reverse=True):
                print(f"  {s:<22} {strat_freq[s]:>12} {strat_pnl[s]:>12,.2f}")

    print()


if __name__ == "__main__":
    main()
