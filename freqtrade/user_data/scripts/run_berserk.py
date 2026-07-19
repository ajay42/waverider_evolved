"""
"Berserk" validation: adversarial head-to-head + component ablation on the
real crash battery, to prove (or disprove) the worth of each piece.

Questions it answers:
  1. Does the Optuna OOS candidate actually protect BETTER than current-live in
     real historical crashes? (candidate vs live)
  2. Does the 5-day age cap earn its keep? (age_cap_off ablation)
  3. Does the wave-period lifecycle earn its keep? (lifecycle_off ablation)
  4. Baseline: governors fully off (the "do nothing" control).

Windows: the two fastest, harshest real crashes (May-2021, LUNA-2022) - chosen
so the whole matrix finishes in a few hours, not overnight.

Modeled on run_tail.py (same subprocess + resume + rename pattern, Windows-safe
.replace). Results: backtest_results/berserk/<window>_<variant>.zip
Analyze: python user_data/scripts/analyze_tail.py --dir berserk

Usage (host, from freqtrade/):  python user_data/scripts/run_berserk.py [--dry]
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
}

# Current-live governor stack (matches config.json wave_rider).
LIVE = {
    "coin_brake_enabled": True, "coin_brake_wave_mult": 1.5,
    "coin_brake_floor_perc": 12.0, "crash_freeze_enabled": True,
    "max_aggregate_exposure_pct": 60, "regime_brake_enabled": True,
    "lifecycle_enabled": True, "max_deal_age_days": 5.0,
}


def _candidate_overrides() -> dict:
    """Trial-8 optimized params from the relearn candidate, governors on."""
    cand_dir = USER_DATA / "matrix_configs" / "candidates"
    files = sorted(cand_dir.glob("*_candidate.json"))
    if not files:
        return None
    params = json.loads(files[-1].read_text())["candidate_wave_rider_params"]
    return {**LIVE, **params}


def build_variants() -> dict:
    v = {
        "live": dict(LIVE),
        "age_cap_off": {**LIVE, "max_deal_age_days": 0},
        "lifecycle_off": {**LIVE, "lifecycle_enabled": False},
        "no_governors": {
            "coin_brake_enabled": False, "crash_freeze_enabled": False,
            "max_aggregate_exposure_pct": 0, "regime_brake_enabled": False,
            "max_deal_age_days": 0, "lifecycle_enabled": True,
        },
    }
    cand = _candidate_overrides()
    if cand:
        v["candidate"] = cand
    return v


def main():
    dry = "--dry" in sys.argv
    base = json.loads((USER_DATA / "config_backtest.json").read_text())
    config_dir = USER_DATA / "matrix_configs"
    config_dir.mkdir(exist_ok=True)
    results_dir = USER_DATA / "backtest_results" / "berserk"
    results_dir.mkdir(parents=True, exist_ok=True)
    variants = build_variants()

    runs = []
    for date, (label, timerange) in WINDOWS.items():
        pairs = json.loads((USER_DATA / "cohorts" / f"{date}_wave.json").read_text())["pairs"]
        for variant, overrides in variants.items():
            run_id = f"{label}_{variant}"
            config = json.loads(json.dumps(base))
            config["exchange"]["pair_whitelist"] = pairs
            config["wave_rider"].update(overrides)
            config["bot_name"] = run_id
            (config_dir / f"{run_id}.json").write_text(json.dumps(config, indent=2))
            runs.append((run_id, timerange))

    print(f"{len(runs)} berserk runs queued ({len(variants)} variants x {len(WINDOWS)} windows)")
    failed = []
    for i, (run_id, timerange) in enumerate(runs, 1):
        if list(results_dir.glob(f"{run_id}*.zip")):
            print(f"[{i}/{len(runs)}] {run_id} already done, skipping", flush=True)
            continue
        cmd = [
            DOCKER, "compose", "run", "--rm", "freqtrade", "backtesting",
            "--config", f"/freqtrade/user_data/matrix_configs/{run_id}.json",
            "--strategy", "WaveRiderDCA", "--timerange", timerange,
            "--timeframe-detail", "1m", "--cache", "none", "--export", "trades",
        ]
        print(f"[{i}/{len(runs)}] {run_id} ...", flush=True)
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
            summary = [l for l in (result.stdout or "").splitlines() if "Total profit %" in l]
            line = summary[0].strip().replace("│", "|") if summary else ""
            print(f"    ok ({took:.0f}s) {line}", flush=True)

    print(f"\ndone: {len(runs) - len(failed)} ok, {len(failed)} failed")
    if failed:
        print("failed:", ", ".join(failed))


if __name__ == "__main__":
    main()
