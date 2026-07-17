"""
Aggregate the stage-1 matrix results into one comparison table.

Reads every user_data/backtest_results/matrix/<regime>_<cohort>_<variant>.zip
and reports, per run:

  profit%        total profit on the 10k wallet
  pnl/cap-day    profit per unit of capital-time actually at risk
                 (profit_abs / sum over trades of stake x days held) - the
                 headline metric: Wave Rider optimises capital efficiency
  dd%            max account drawdown
  zombie$        PnL of phase_d_close exits (the capitulation bill)
  zombie-days    capital-days locked in deals that ended in Phase D
  harvest$       PnL of all profitable machinery (grace/skim/grid exits)
  trades         closed-trade count (force_exit = window-end artifacts,
                 shown separately so they don't pollute the comparison)

Usage:
    python user_data/scripts/analyze_matrix.py
"""

import glob
import json
import zipfile
from collections import defaultdict
from datetime import datetime
from pathlib import Path

MATRIX_DIR = Path(__file__).resolve().parents[1] / "backtest_results" / "matrix"

HARVEST = {"grace_full_close", "skim_full_close", "skim_close",
           "grid_full_close", "grid_close"}


def parse_run(path: Path) -> dict:
    with zipfile.ZipFile(path) as z:
        name = [n for n in z.namelist()
                if n.endswith(".json") and "meta" not in n and "config" not in n][0]
        data = json.loads(z.read(name))
    res = list(data["strategy"].values())[0]
    trades = res["trades"]

    profit_abs = res["profit_total_abs"]
    profit_pct = res["profit_total"] * 100
    dd_pct = (res.get("max_drawdown_account") or 0) * 100

    capital_days = 0.0
    zombie_days = 0.0
    reason_pnl = defaultdict(float)
    reason_cnt = defaultdict(int)
    for t in trades:
        open_dt = datetime.fromisoformat(t["open_date"])
        close_dt = datetime.fromisoformat(t["close_date"])
        days = max((close_dt - open_dt).total_seconds() / 86400, 1 / 288)
        # max_stake_amount reflects the ladder's peak commitment
        stake = t.get("max_stake_amount") or t["stake_amount"]
        capital_days += stake * days
        reason = t["exit_reason"]
        reason_pnl[reason] += t["profit_abs"]
        reason_cnt[reason] += 1
        if reason == "phase_d_close":
            zombie_days += stake * days

    return {
        "profit_pct": profit_pct,
        "profit_abs": profit_abs,
        "pnl_per_capday": profit_abs / capital_days if capital_days else 0.0,
        "dd_pct": dd_pct,
        "zombie_pnl": reason_pnl.get("phase_d_close", 0.0),
        "zombie_days": zombie_days,
        "harvest_pnl": sum(v for k, v in reason_pnl.items() if k in HARVEST),
        "n_trades": sum(reason_cnt.values()),
        "n_forced": reason_cnt.get("force_exit", 0),
        "reasons": dict(reason_pnl),
    }


def main():
    runs = {}
    for path in sorted(glob.glob(str(MATRIX_DIR / "*.zip"))):
        run_id = Path(path).stem.replace("backtest-result-", "")
        try:
            runs[run_id] = parse_run(Path(path))
        except Exception as exc:
            print(f"skip {run_id}: {exc}")

    if not runs:
        print("no matrix results found")
        return

    header = (f"{'run':<28} {'profit%':>8} {'pnl/capday':>11} {'dd%':>6} "
              f"{'harvest$':>9} {'zombie$':>8} {'zombie-cd':>9} {'trades':>6} {'forced':>6}")
    current_regime = None
    for run_id in sorted(runs):
        regime = run_id.split("_")[0]
        if regime != current_regime:
            print(f"\n=== {regime.upper()} ===")
            print(header)
            current_regime = regime
        r = runs[run_id]
        print(f"{run_id:<28} {r['profit_pct']:>7.2f}% {r['pnl_per_capday']:>10.4f} "
              f"{r['dd_pct']:>5.2f}% {r['harvest_pnl']:>8.2f} {r['zombie_pnl']:>8.2f} "
              f"{r['zombie_days']:>9.0f} {r['n_trades']:>6} {r['n_forced']:>6}")

    # Grace value: profit(life_wr_first) - profit(life_no_grace) per group.
    # Positive = the DCA grace window earned more than the skims it
    # suppressed; negative = grace's opportunity cost exceeded its premium.
    print("\n=== GRACE VALUE (life_wr_first minus life_no_grace, USD) ===")
    for (regime, cohort) in sorted({tuple(r.split("_")[:2]) for r in runs}):
        with_grace = runs.get(f"{regime}_{cohort}_life_wr_first")
        no_grace = runs.get(f"{regime}_{cohort}_life_no_grace")
        if with_grace and no_grace:
            diff = with_grace["profit_abs"] - no_grace["profit_abs"]
            print(f"  {regime:<5} {cohort:<7} {diff:+8.2f}  "
                  f"(grace closes: {with_grace['reasons'].get('grace_full_close', 0.0):+.2f})")

    # cross-regime consistency: average pnl/capday rank per variant
    print("\n=== CROSS-REGIME CONSISTENCY (avg rank by pnl/cap-day, lower = better) ===")
    by_group = defaultdict(list)
    for run_id, r in runs.items():
        regime, cohort, *variant = run_id.split("_")
        by_group[(regime, cohort)].append(("_".join(variant), r["pnl_per_capday"]))
    ranks = defaultdict(list)
    for (regime, cohort), entries in by_group.items():
        entries.sort(key=lambda e: e[1], reverse=True)
        for rank, (variant, _) in enumerate(entries, 1):
            ranks[variant].append(rank)
    for variant, rr in sorted(ranks.items(), key=lambda kv: sum(kv[1]) / len(kv[1])):
        print(f"  {variant:<18} avg rank {sum(rr) / len(rr):.2f}  (ranks: {rr})")


if __name__ == "__main__":
    main()
