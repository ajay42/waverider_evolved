"""
Stage-2A: ladder-geometry sweep, walk-forward style.

TRAIN on 2022 windows (bear2022b + ftxchop, data already on disk), pick the
top geometries, VALIDATE on the held-out 2026 windows (bear + chop from the
stage-1 matrix). Sweeping the two axes stage-1 never touched:

    safety_order_price_deviation_perc in {1.0, 2.0, 3.0}
    safety_order_volume_scale        in {1.05, 1.10}

= 6 geometries x 2 train windows = 12 runs. Base = the proven config
(life_grid_first, all governors, brake m15). Validation runs are launched
separately after inspection (--validate g<id> flag).

Usage:
    python user_data/scripts/run_stage2.py            # train runs
    python user_data/scripts/run_stage2.py --validate d2_v105  (etc.)
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

TRAIN_WINDOWS = {
    "20220613": ("bear2022b", "20220613-20220712"),
    "20220917": ("ftxchop", "20220917-20221108"),
}
VALIDATE_WINDOWS = {
    "20260602": ("val-bear26", "20260602-20260701"),
    "20260302": ("val-chop26", "20260302-20260425"),
}

GEOMETRIES = {}
for dev in (1.0, 2.0, 3.0):
    for vol in (1.05, 1.10):
        gid = f"d{int(dev)}_v{int(vol * 100)}"
        GEOMETRIES[gid] = {
            "safety_order_price_deviation_perc": dev,
            "safety_order_volume_scale": vol,
        }

SAFETY_BASE = {
    "coin_brake_enabled": True, "coin_brake_wave_mult": 1.5,
    "crash_freeze_enabled": True, "max_aggregate_exposure_pct": 60,
    "regime_brake_enabled": True,
}


def run_one(run_id: str, timerange: str, pairs: list, overrides: dict,
            results_dir: Path) -> bool:
    config_dir = USER_DATA / "matrix_configs"
    base = json.loads((USER_DATA / "config_backtest.json").read_text())
    config = json.loads(json.dumps(base))
    config["exchange"]["pair_whitelist"] = pairs
    config["wave_rider"].update(SAFETY_BASE)
    config["wave_rider"].update(overrides)
    config["bot_name"] = run_id
    (config_dir / f"{run_id}.json").write_text(json.dumps(config, indent=2))

    if list(results_dir.glob(f"{run_id}*.zip")):
        print(f"  {run_id} already done, skipping", flush=True)
        return True
    cmd = [DOCKER, "compose", "run", "--rm", "freqtrade", "backtesting",
           "--config", f"/freqtrade/user_data/matrix_configs/{run_id}.json",
           "--strategy", "WaveRiderDCA", "--timerange", timerange,
           "--timeframe-detail", "1m", "--cache", "none", "--export", "trades"]
    started = time.time()
    result = subprocess.run(cmd, cwd=FREQTRADE_DIR, capture_output=True,
                            text=True, encoding="utf-8", errors="replace")
    took = time.time() - started
    if result.returncode != 0:
        tail = (result.stdout + result.stderr).strip().splitlines()[-3:]
        print(f"  {run_id} FAILED ({took:.0f}s): " + " | ".join(tail), flush=True)
        return False
    produced = sorted((USER_DATA / "backtest_results").glob("backtest-result-*.zip"))
    if produced:
        newest = produced[-1]
        newest.rename(results_dir / f"{run_id}.zip")
        meta = newest.with_name(newest.name.replace(".zip", ".meta.json"))
        if meta.exists():
            meta.rename(results_dir / f"{run_id}.meta.json")
    summary = [l for l in (result.stdout or "").splitlines() if "Total profit %" in l]
    print(f"  {run_id} ok ({took:.0f}s) "
          f"{summary[0].strip().replace(chr(0x2502), '|') if summary else ''}", flush=True)
    return True


# Stage-2B (Ajay's experiment): ONLY the best coins - top-5 cohorts -
# with per-coin dynamic geometry (spacing/TP = mult x that coin's own
# amplitude, frozen at deal start).
BEST5 = {
    "best5_static": {},  # top-5 concentration, standard 2%/1.1 geometry
    "best5_dyn_a": {"dynamic_ladder_enabled": True,
                    "dynamic_spacing_mult": 0.4, "dynamic_tp_mult": 0.4},
    "best5_dyn_b": {"dynamic_ladder_enabled": True,
                    "dynamic_spacing_mult": 0.6, "dynamic_tp_mult": 0.5},
}


def main():
    results_dir = USER_DATA / "backtest_results" / "stage2"
    results_dir.mkdir(parents=True, exist_ok=True)

    if "--validate" in sys.argv:
        gid = sys.argv[sys.argv.index("--validate") + 1]
        pool = dict(GEOMETRIES)
        pool.update(BEST5)
        runs = [(date, lt, gid, pool[gid],
                 "wave5" if gid.startswith("best5") else "wave")
                for date, lt in VALIDATE_WINDOWS.items()]
    else:
        runs = []
        for date, lt in TRAIN_WINDOWS.items():
            for gid, ov in GEOMETRIES.items():
                runs.append((date, lt, gid, ov, "wave"))
            for gid, ov in BEST5.items():
                runs.append((date, lt, gid, ov, "wave5"))

    print(f"stage-2: {len(runs)} runs queued")
    for i, (date, (label, timerange), gid, overrides, kind) in enumerate(runs, 1):
        cohort = json.loads((USER_DATA / "cohorts" / f"{date}_{kind}.json").read_text())["pairs"]
        print(f"[{i}/{len(runs)}] {label}_{gid} ...", flush=True)
        run_one(f"{label}_{gid}", timerange, cohort, overrides, results_dir)
    print("done")


if __name__ == "__main__":
    main()
