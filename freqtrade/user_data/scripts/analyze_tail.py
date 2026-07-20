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
import sys
import zipfile
from collections import defaultdict
from datetime import datetime
from pathlib import Path

RESULTS_ROOT = Path(__file__).resolve().parents[1] / "backtest_results"
# Default to the tail runs; --dir <name> reuses this exact analysis on any
# result set with the same schema (e.g. --dir synthetic).
_dir = "tail"
if "--dir" in sys.argv:
    _dir = sys.argv[sys.argv.index("--dir") + 1]
TAIL_DIR = RESULTS_ROOT / _dir
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


# Known variant suffixes (tail + synthetic). Longest-first so e.g.
# "all_m15_v105" is stripped before "all_m15".
VARIANT_SUFFIXES = [
    "no_governors", "all_m15_v105", "brake_only_m15", "freeze_agg_fixed",
    "all_m15", "all_on",
    # berserk battery
    "age_cap_off", "lifecycle_off", "candidate", "live",
    # profit battery (levers #3/#4)
    "waveup", "conc_deep", "conc_big",
]
# The "governors ON" variant name differs by result set (tail uses all_m15,
# synthetic uses all_on) - try each.
ON_VARIANTS = ["all_m15", "all_on"]


def split_window_variant(run_id: str):
    """Return (window, variant) by stripping a known variant suffix; scenario
    names may themselves contain underscores, so we can't just split on '_'."""
    for suf in VARIANT_SUFFIXES:
        if run_id.endswith("_" + suf):
            return run_id[: -(len(suf) + 1)], suf
    return run_id.rsplit("_", 1)[0], run_id.rsplit("_", 1)[-1]


def main():
    runs = {}
    for path in sorted(glob.glob(str(TAIL_DIR / "*.zip"))):
        run_id = Path(path).stem
        try:
            runs[run_id] = parse_run(Path(path))
        except Exception as exc:
            print(f"skip {run_id}: {exc}")
    if not runs:
        print(f"no results found in {TAIL_DIR}")
        return

    header = (f"{'run':<34} {'profit%':>8} {'dd%':>6} {'peak$':>8} {'peak%':>6} "
              f"{'capit$':>8} {'n':>3} {'grid#':>5} {'trades':>6}")
    current = None
    for run_id in sorted(runs):
        window, _ = split_window_variant(run_id)
        if window != current:
            print(f"\n=== {window.upper()} ===")
            print(header)
            current = window
        r = runs[run_id]
        print(f"{run_id:<34} {r['profit_pct']:>7.2f}% {r['dd_pct']:>5.2f}% "
              f"{r['peak_deploy']:>8.0f} {r['peak_deploy_pct']:>5.1f}% "
              f"{r['capit_pnl']:>8.2f} {r['capit_n']:>3} {r['grid_n']:>5} {r['trades']:>6}")

    # Acceptance check: with all governors on, peak deployment <= ~60%.
    print("\n=== ACCEPTANCE (governors ON vs no_governors, peak deployment %) ===")
    windows = sorted({split_window_variant(r)[0] for r in runs})
    for window in windows:
        off = runs.get(f"{window}_no_governors")
        on = next((runs[f"{window}_{v}"] for v in ON_VARIANTS
                   if f"{window}_{v}" in runs), None)
        if on and off:
            verdict = "PASS" if on["peak_deploy_pct"] <= 62 else "FAIL"
            print(f"  {window:<22} governors OFF {off['peak_deploy_pct']:5.1f}%  "
                  f"-> ON {on['peak_deploy_pct']:5.1f}%   [{verdict}]")


if __name__ == "__main__":
    main()
