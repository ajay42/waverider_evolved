"""
Tail-window safety backtests (CAPITAL_SAFETY.md "Backtest plan").

Prove the TAIL, not the body: worst-case aggregate deployment and portfolio
drawdown through historical correlated crashes, isolating each governor's
contribution. Wave cohorts only (the live habitat).

Windows (mechanically classified): May-2021 crash, the two 2022 bears
(LUNA era), and the Sep-Nov 2022 chop ending at FTX.

Variants: governors off (baseline) / all governors at brake-mult 1.5, 2.0,
2.5 / brake only / freeze+aggregate only / all + volume_scale 1.05.

= 4 windows x 7 variants = 28 runs. Results:
user_data/backtest_results/tail/<window>_<variant>.zip

Usage (host, from freqtrade/):
    python user_data/scripts/run_tail.py [--dry]
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
    "20220505": ("bear2022a", "20220505-20220605"),
    "20220613": ("bear2022b", "20220613-20220712"),
    "20220917": ("ftxchop", "20220917-20221108"),
}

GOVERNORS_OFF = {
    "coin_brake_enabled": False, "crash_freeze_enabled": False,
    "max_aggregate_exposure_pct": 0, "regime_brake_enabled": False,
}
ALL_ON = {
    "coin_brake_enabled": True, "crash_freeze_enabled": True,
    "max_aggregate_exposure_pct": 60, "regime_brake_enabled": True,
}
VARIANTS = {
    # Slim sweep for run 2 (post data-gap fix): m20/m25 dropped - run 1
    # showed m15 ~= m20 and m25 worse; see tail-safety-report finding 3.
    "no_governors": dict(GOVERNORS_OFF),
    "all_m15": dict(ALL_ON, coin_brake_wave_mult=1.5),
    "brake_only_m15": dict(GOVERNORS_OFF, coin_brake_enabled=True,
                           coin_brake_wave_mult=1.5),
    "freeze_agg_fixed": dict(ALL_ON, coin_brake_enabled=False),
    "all_m15_v105": dict(ALL_ON, coin_brake_wave_mult=1.5,
                         safety_order_volume_scale=1.05),
}


def main():
    dry = "--dry" in sys.argv
    base = json.loads((USER_DATA / "config_backtest.json").read_text())
    config_dir = USER_DATA / "matrix_configs"
    config_dir.mkdir(exist_ok=True)
    results_dir = USER_DATA / "backtest_results" / "tail"
    results_dir.mkdir(parents=True, exist_ok=True)

    runs = []
    for date, (label, timerange) in WINDOWS.items():
        cohort_file = USER_DATA / "cohorts" / f"{date}_wave.json"
        pairs = json.loads(cohort_file.read_text())["pairs"]
        # BTC is the regime reference - must be in the whitelist's data scope
        # for informative_pairs to resolve in backtesting.
        for variant, overrides in VARIANTS.items():
            run_id = f"{label}_{variant}"
            config = json.loads(json.dumps(base))
            config["exchange"]["pair_whitelist"] = pairs
            config["wave_rider"].update(overrides)
            config["bot_name"] = run_id
            (config_dir / f"{run_id}.json").write_text(json.dumps(config, indent=2))
            runs.append((run_id, timerange))

    print(f"{len(runs)} tail runs queued")
    failed = []
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
                newest.rename(results_dir / f"{run_id}.zip")
                meta = newest.with_name(newest.name.replace(".zip", ".meta.json"))
                if meta.exists():
                    meta.rename(results_dir / f"{run_id}.meta.json")
            summary = [l for l in (result.stdout or "").splitlines() if "Total profit %" in l]
            line = summary[0].strip().replace("│", "|") if summary else ""
            print(f"    ok ({took:.0f}s) {line}", flush=True)

    print(f"\ndone: {len(runs) - len(failed)} ok, {len(failed)} failed")
    if failed:
        print("failed:", ", ".join(failed))


if __name__ == "__main__":
    main()
