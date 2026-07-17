"""
Analyze the tail-window safety runs (CAPITAL_SAFETY.md acceptance).

Primary metrics — prove the TAIL, not the body:
  peak-deploy$   worst-case CONCURRENT deployment (event-sweep over every
                 trade's [open, close] interval at its max stake) - the
                 number the 60% ceiling must hold down
  peak-deploy%   same, as % of the 10k wallet
  dd%            max account drawdown
  profit%        window profit (secondary here - this is a safety test)
  capit$ / n     Phase D capitulation PnL and count
  braked-style exits: grid_close counts (brake/freeze/lifecycle all route
                 through the grid; the comparison across variants isolates
                 each governor's effect)

Usage:
    python user_data/scripts/analyze_tail.py
"""

import glob
import json
import zipfile
from collections import defaultdict
from datetime import datetime
from pathlib import Path

TAIL_DIR = Path(__file__).resolve().parents[1] / "backtest_results" / "tail"
WALLET = 10_000.0


def parse_run(path: Path) -> dict:
    with zipfile.ZipFile(path) as z:
        name = [n for n in z.namelist()
                if n.endswith(".json") and "meta" not in n and "config" not in n][0]
        data = json.loads(z.read(name))
    res = list(data["strategy"].values())[0]
    trades = res["trades"]

    # Event sweep for peak concurrent deployment (each trade weighted at its
    # maximum stake for its whole open interval - slightly conservative).
    events = []
    for t in trades:
        stake = t.get("max_stake_amount") or t["stake_amount"]
        events.append((datetime.fromisoformat(t["open_date"]), stake))
        events.append((datetime.fromisoformat(t["close_date"]), -stake))
    events.sort(key=lambda e: e[0])
    running = peak = 0.0
    for _, delta in events:
        running += delta
        peak = max(peak, running)

    reasons = defaultdict(float)
    counts = defaultdict(int)
    for t in trades:
        reasons[t["exit_reason"]] += t["profit_abs"]
        counts[t["exit_reason"]] += 1

    return {
        "profit_pct": res["profit_total"] * 100,
        "dd_pct": (res.get("max_drawdown_account") or 0) * 100,
        "peak_deploy": peak,
        "peak_deploy_pct": 100.0 * peak / WALLET,
        "capit_pnl": reasons.get("phase_d_close", 0.0),
        "capit_n": counts.get("phase_d_close", 0),
        "grid_n": counts.get("grid_close", 0) + counts.get("grid_full_close", 0),
        "trades": len(trades),
    }


def main():
    runs = {}
    for path in sorted(glob.glob(str(TAIL_DIR / "*.zip"))):
        run_id = Path(path).stem
        try:
            runs[run_id] = parse_run(Path(path))
        except Exception as exc:
            print(f"skip {run_id}: {exc}")
    if not runs:
        print("no tail results found")
        return

    header = (f"{'run':<28} {'profit%':>8} {'dd%':>6} {'peak$':>8} {'peak%':>6} "
              f"{'capit$':>8} {'n':>3} {'grid#':>5} {'trades':>6}")
    current = None
    for run_id in sorted(runs):
        window = run_id.split("_")[0]
        if window != current:
            print(f"\n=== {window.upper()} ===")
            print(header)
            current = window
        r = runs[run_id]
        print(f"{run_id:<28} {r['profit_pct']:>7.2f}% {r['dd_pct']:>5.2f}% "
              f"{r['peak_deploy']:>8.0f} {r['peak_deploy_pct']:>5.1f}% "
              f"{r['capit_pnl']:>8.2f} {r['capit_n']:>3} {r['grid_n']:>5} {r['trades']:>6}")

    # Acceptance check: with all governors on, peak deployment <= ~60%.
    print("\n=== ACCEPTANCE (all_m15 vs no_governors, peak deployment %) ===")
    for window in sorted({r.split("_")[0] for r in runs}):
        on = runs.get(f"{window}_all_m15")
        off = runs.get(f"{window}_no_governors")
        if on and off:
            verdict = "PASS" if on["peak_deploy_pct"] <= 62 else "FAIL"
            print(f"  {window:<12} governors OFF {off['peak_deploy_pct']:5.1f}%  "
                  f"-> ON {on['peak_deploy_pct']:5.1f}%   [{verdict}]")


if __name__ == "__main__":
    main()
