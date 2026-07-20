"""
Profit exploration battery: levers #3 (selection-for-profit) and #4
(controlled concentration), tested against the live baseline with FULL
safety stack on - profit is only accepted if drawdown/deployment hold.

Variants (all governors ON, 5-day age cap ON - the proven live stack):
  live          baseline: wave cohort (10 coins), live geometry
  waveup        #3: WAVEUP cohort (chop + gentle updrift), live geometry
  conc_deep     #4a: top-5 of wave cohort, per-coin cap x2 - same $10 orders
                (bigger bets via DEEPER ladders: ~2x the rungs fit)
  conc_big      #4b: top-5, cap x2, orders x2 ($20 BO/SO - same ladder
                depth, double the size per rung)

Windows: 3 train-era (crash2021, bear2022b, ftxchop) + 2 hold-out 2026
(val-chop26, val-bear26). Verdict rule: a lever wins only if it beats
baseline profit AND keeps dd/peak-deployment within the safety envelope
(no trading more risk for return - CAPITAL_SAFETY.md).

Results: backtest_results/profit/<window>_<variant>.zip
Analyze: python user_data/scripts/analyze_tail.py --dir profit
Usage:   python user_data/scripts/run_profit.py [--dry]
"""

import json
import subprocess
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

FREQTRADE_DIR = Path(__file__).resolve().parents[2]
USER_DATA = FREQTRADE_DIR / "user_data"
DOCKER = r"C:\Program Files\Docker\Docker\resources\bin\docker.exe"

WINDOWS = {
    "20210512": ("crash2021", "20210512-20210613"),
    "20220613": ("bear2022b", "20220613-20220712"),
    "20220917": ("ftxchop", "20220917-20221108"),
    "20260302": ("valchop26", "20260302-20260425"),
    "20260602": ("valbear26", "20260602-20260701"),
}

SAFETY = {
    "coin_brake_enabled": True, "coin_brake_wave_mult": 1.5,
    "crash_freeze_enabled": True, "max_aggregate_exposure_pct": 60,
    "regime_brake_enabled": True, "lifecycle_enabled": True,
    "max_deal_age_days": 5.0,
}

# variant -> (cohort_kind, top_n or None, overrides)
VARIANTS = {
    "live":      ("wave",   None, dict(SAFETY)),
    "waveup":    ("waveup", None, dict(SAFETY)),
    "conc_deep": ("wave",   5,    dict(SAFETY, max_exposure_per_coin_usd=2000.0,
                                       max_coins=5)),
    "conc_big":  ("wave",   5,    dict(SAFETY, max_exposure_per_coin_usd=2000.0,
                                       max_coins=5, base_order_size_usd=20.0,
                                       safety_order_size_usd=20.0)),
}


def main():
    dry = "--dry" in sys.argv
    base = json.loads((USER_DATA / "config_backtest.json").read_text())
    config_dir = USER_DATA / "matrix_configs"
    config_dir.mkdir(exist_ok=True)
    results_dir = USER_DATA / "backtest_results" / "profit"
    results_dir.mkdir(parents=True, exist_ok=True)

    runs = []
    for date, (label, timerange) in WINDOWS.items():
        for variant, (kind, top_n, overrides) in VARIANTS.items():
            cohort_file = USER_DATA / "cohorts" / f"{date}_{kind}.json"
            if not cohort_file.exists():
                print(f"  SKIP {label}_{variant}: no cohort {cohort_file.name}")
                continue
            pairs = json.loads(cohort_file.read_text())["pairs"]
            if top_n:
                pairs = pairs[:top_n]
            run_id = f"{label}_{variant}"
            config = json.loads(json.dumps(base))
            config["exchange"]["pair_whitelist"] = pairs
            config["wave_rider"].update(overrides)
            config["bot_name"] = run_id
            (config_dir / f"{run_id}.json").write_text(json.dumps(config, indent=2))
            runs.append((run_id, timerange, len(pairs)))

    print(f"{len(runs)} profit runs queued")
    failed = []
    for i, (run_id, timerange, n_pairs) in enumerate(runs, 1):
        if list(results_dir.glob(f"{run_id}*.zip")):
            print(f"[{i}/{len(runs)}] {run_id} already done, skipping", flush=True)
            continue
        cmd = [
            DOCKER, "compose", "run", "--rm", "freqtrade", "backtesting",
            "--config", f"/freqtrade/user_data/matrix_configs/{run_id}.json",
            "--strategy", "WaveRiderDCA", "--timerange", timerange,
            "--timeframe-detail", "1m", "--cache", "none", "--export", "trades",
        ]
        print(f"[{i}/{len(runs)}] {run_id} ({n_pairs} pairs) ...", flush=True)
        if dry:
            continue
        started = time.time()
        result = subprocess.run(cmd, cwd=FREQTRADE_DIR, capture_output=True,
                                text=True, encoding="utf-8", errors="replace")
        took = time.time() - started
        if result.returncode != 0:
            failed.append(run_id)
            tail = (result.stdout + result.stderr).strip().splitlines()[-4:]
            print(f"    FAILED ({took:.0f}s): " + " | ".join(tail), flush=True)
        else:
            produced = sorted((USER_DATA / "backtest_results").glob("backtest-result-*.zip"))
            if produced:
                newest = produced[-1]
                newest.replace(results_dir / f"{run_id}.zip")
                meta = newest.with_name(newest.name.replace(".zip", ".meta.json"))
                if meta.exists():
                    meta.replace(results_dir / f"{run_id}.meta.json")
            summary = [l for l in (result.stdout or "").splitlines()
                       if "Total profit %" in l]
            line = summary[0].strip().replace("│", "|") if summary else ""
            print(f"    ok ({took:.0f}s) {line}", flush=True)

    print(f"\ndone: {len(runs) - len(failed)} ok, {len(failed)} failed")
    if failed:
        print("failed:", ", ".join(failed))


if __name__ == "__main__":
    main()
