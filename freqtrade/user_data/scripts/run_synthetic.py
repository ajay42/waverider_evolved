"""
Tier-B synthetic stress backtests: run the FULL live system (all governors,
the wave-period lifecycle, the BTC crash-freeze) against the beyond-history
shock scenarios curated by Tier A and materialized by gen_synthetic_data.py.

For each shortlisted scenario we run governors OFF vs ALL-ON, so the report
isolates exactly how much the safety stack reduces the capital trap the raw
mechanic showed in Tier A. Modeled on run_tail.py (same subprocess + resume
pattern); the only additions are a per-scenario --datadir and --timerange
pulled from the synthetic manifest.

Results: user_data/backtest_results/synthetic/<scenario>_<variant>.zip
Analyze with:  python user_data/scripts/analyze_tail.py --dir synthetic

Usage (host, from freqtrade/):
    python user_data/scripts/run_synthetic.py [--dry]
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
SYN_DIR = USER_DATA / "data" / "binance_synthetic"

GOVERNORS_OFF = {
    "coin_brake_enabled": False, "crash_freeze_enabled": False,
    "max_aggregate_exposure_pct": 0, "regime_brake_enabled": False,
}
ALL_ON = {
    "coin_brake_enabled": True, "crash_freeze_enabled": True,
    "max_aggregate_exposure_pct": 60, "regime_brake_enabled": True,
    "coin_brake_wave_mult": 1.5,
}
VARIANTS = {"no_governors": GOVERNORS_OFF, "all_on": ALL_ON}


def main():
    dry = "--dry" in sys.argv
    manifest = json.loads((SYN_DIR / "manifest.json").read_text())
    base = json.loads((USER_DATA / "config_backtest.json").read_text())
    config_dir = USER_DATA / "matrix_configs"
    config_dir.mkdir(exist_ok=True)
    results_dir = USER_DATA / "backtest_results" / "synthetic"
    results_dir.mkdir(parents=True, exist_ok=True)

    runs = []
    for scen, info in manifest.items():
        for variant, overrides in VARIANTS.items():
            run_id = f"{scen}_{variant}"
            config = json.loads(json.dumps(base))
            config["exchange"]["pair_whitelist"] = info["pairs"]
            config["wave_rider"].update(overrides)
            config["bot_name"] = run_id
            (config_dir / f"{run_id}.json").write_text(json.dumps(config, indent=2))
            runs.append((run_id, scen, info["timerange"]))

    print(f"{len(runs)} synthetic runs queued")
    failed = []
    for i, (run_id, scen, timerange) in enumerate(runs, 1):
        if list(results_dir.glob(f"{run_id}*.zip")):
            print(f"[{i}/{len(runs)}] {run_id} already done, skipping", flush=True)
            continue
        # Freqtrade uses --datadir AS-IS (it only appends the exchange name when
        # no --datadir is given), so point it straight at the folder holding the
        # feathers: .../<scen>/binance/.
        datadir = f"/freqtrade/user_data/data/binance_synthetic/{scen}/binance"
        cmd = [
            DOCKER, "compose", "run", "--rm", "freqtrade", "backtesting",
            "--config", f"/freqtrade/user_data/matrix_configs/{run_id}.json",
            "--strategy", "WaveRiderDCA",
            "--datadir", datadir,
            "--timerange", timerange,
            "--timeframe-detail", "1m",
            "--cache", "none",
            "--export", "trades",
        ]
        print(f"[{i}/{len(runs)}] {run_id} ({timerange}) ...", flush=True)
        if dry:
            continue
        started = time.time()
        result = subprocess.run(cmd, cwd=FREQTRADE_DIR, capture_output=True,
                                text=True, encoding="utf-8", errors="replace")
        took = time.time() - started
        if result.returncode != 0:
            failed.append(run_id)
            tail_lines = (result.stdout + result.stderr).strip().splitlines()[-5:]
            print(f"    FAILED ({took:.0f}s): " + " | ".join(tail_lines), flush=True)
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
