"""
Stage-1 backtest matrix runner (DESIGN.md section 7).

Runs every combination of:
  * 3 regime windows (bull / chop / bear, found by find_regime_windows.py)
  * 2 cohorts per window (wave = live selector's picks, volume = control)
  * 5 strategy variants (the DESIGN QUESTIONS, not parameter tuning):
      pure_wr         - the original spec: outer-pair skims only
      wr_combo_rec    - best-combo + recycling, no lifecycle
      life_wr_first   - full lifecycle, Wave Rider before grid
      life_grid_first - full lifecycle, grid before Wave Rider
      life_no_grace   - lifecycle without the DCA grace window

= 30 runs, sequential (each is minutes with --timeframe-detail 1m).
Results land in user_data/backtest_results/matrix/<window>_<cohort>_<variant>.zip
Analyze with analyze_matrix.py afterwards.

Usage (from the freqtrade/ folder on the host):
    python user_data/scripts/run_matrix.py [--only life_wr_first] [--dry]
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
    "20241106": ("bull", "20241106-20241210"),
    "20260302": ("chop", "20260302-20260425"),
    "20260602": ("bear", "20260602-20260701"),
}
COHORTS = ("wave", "volume")
VARIANTS = {
    "pure_wr": {
        "lifecycle_enabled": False, "combo_selection": "outer_pair",
        "recycle_last_so": False,
    },
    "wr_combo_rec": {
        "lifecycle_enabled": False, "combo_selection": "best_combo",
        "recycle_last_so": True,
    },
    "life_wr_first": {
        "lifecycle_enabled": True, "phase_order": "wr,grid",
        "combo_selection": "best_combo", "recycle_last_so": True,
    },
    "life_grid_first": {
        "lifecycle_enabled": True, "phase_order": "grid,wr",
        "combo_selection": "best_combo", "recycle_last_so": True,
    },
    "life_no_grace": {
        "lifecycle_enabled": True, "phase_order": "wr,grid", "grace_waves": 0.0,
        "combo_selection": "best_combo", "recycle_last_so": True,
    },
}


def main():
    only = sys.argv[sys.argv.index("--only") + 1] if "--only" in sys.argv else None
    dry = "--dry" in sys.argv

    base = json.loads((USER_DATA / "config_backtest.json").read_text())
    config_dir = USER_DATA / "matrix_configs"
    config_dir.mkdir(exist_ok=True)
    (USER_DATA / "backtest_results" / "matrix").mkdir(parents=True, exist_ok=True)

    runs = []
    for date, (regime, timerange) in WINDOWS.items():
        for cohort in COHORTS:
            cohort_pairs = json.loads(
                (USER_DATA / "cohorts" / f"{date}_{cohort}.json").read_text())["pairs"]
            for variant, overrides in VARIANTS.items():
                if only and variant != only:
                    continue
                run_id = f"{regime}_{cohort}_{variant}"
                config = json.loads(json.dumps(base))  # deep copy
                config["exchange"]["pair_whitelist"] = cohort_pairs
                config["wave_rider"].update(overrides)
                config["bot_name"] = run_id
                config_path = config_dir / f"{run_id}.json"
                config_path.write_text(json.dumps(config, indent=2))
                runs.append((run_id, timerange))

    print(f"{len(runs)} runs queued")
    failed = []
    results_dir = USER_DATA / "backtest_results" / "matrix"
    for i, (run_id, timerange) in enumerate(runs, 1):
        if list(results_dir.glob(f"{run_id}*.zip")):
            print(f"[{i}/{len(runs)}] {run_id} already done, skipping", flush=True)
            continue
        cmd = [
            DOCKER, "compose", "run", "--rm", "freqtrade", "backtesting",
            "--config", f"/freqtrade/user_data/matrix_configs/{run_id}.json",
            "--strategy", "WaveRiderDCA",
            "--timerange", timerange,
            "--timeframe-detail", "1m",
            "--cache", "none",
            "--export", "trades",
        ]
        print(f"[{i}/{len(runs)}] {run_id} ...", flush=True)
        if dry:
            continue
        started = time.time()
        # Windows consoles default to cp1252; freqtrade's rich tables are
        # UTF-8 - decode explicitly or capture dies mid-run.
        result = subprocess.run(cmd, cwd=FREQTRADE_DIR, capture_output=True,
                                text=True, encoding="utf-8", errors="replace")
        took = time.time() - started
        if result.returncode != 0:
            failed.append(run_id)
            tail = (result.stdout + result.stderr).strip().splitlines()[-5:]
            print(f"    FAILED ({took:.0f}s): " + " | ".join(tail), flush=True)
        else:
            # claim the default-named export as this run's result
            produced = sorted((USER_DATA / "backtest_results").glob("backtest-result-*.zip"))
            if produced:
                newest = produced[-1]
                newest.rename(results_dir / f"{run_id}.zip")
                meta = newest.with_name(newest.name.replace(".zip", ".meta.json"))
                if meta.exists():
                    meta.rename(results_dir / f"{run_id}.meta.json")
            summary = [l for l in (result.stdout or "").splitlines() if "Total profit %" in l]
            line = summary[0].strip().replace("│", "|") if summary else ""
            print(f"    ok ({took:.0f}s) {line}", flush=True)

    print(f"\ndone: {len(runs) - len(failed)} ok, {len(failed)} failed")
    if failed:
        print("failed runs:", ", ".join(failed))


if __name__ == "__main__":
    main()
