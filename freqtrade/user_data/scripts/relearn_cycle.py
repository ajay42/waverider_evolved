"""
Offline re-learning orchestrator (Item 4) - INERT OUTPUT ONLY.

Ties the pieces together into one manual/periodic "re-learn" pass:
  1. rebuild the deal dataset + refit the win-probability model (Item 3) on
     the latest backtest data;
  2. read the walk-forward Optuna validation results (Item 2) and pick the
     best candidate that ALSO holds up out-of-sample AND passes the capital-
     safety gates;
  3. emit ONE candidate config (the wave_rider param diff vs the live config)
     to matrix_configs/candidates/<date>_candidate.json, with a mandatory
     human review + deploy checklist.

CRITICAL SAFETY PROPERTY: this script NEVER writes config.json and NEVER
restarts a container. It only produces a proposal. Promoting a candidate to
live is a deliberate human step that must pass the same gate as any other
config change (see RELEARNING.md). This is the offline-only design Ajay
approved; a live/online self-adjusting bot was explicitly rejected for now.

By default it consumes EXISTING Optuna results (cheap, no Docker). Pass
--search N to also run N new train-search trials first (needs Docker + venv).

Run (host, from freqtrade/):
    python user_data/scripts/relearn_cycle.py
"""

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

USER_DATA = Path(__file__).resolve().parents[1]
SCRIPTS = USER_DATA / "scripts"
LIVE_CONFIG = USER_DATA / "config.json"
VALIDATION = USER_DATA / "optuna_validation.json"
CAND_DIR = USER_DATA / "matrix_configs" / "candidates"
VENV_PY = USER_DATA.parent / ".venv-tools" / "Scripts" / "python.exe"

# Safety gates a candidate MUST pass on the held-out validate windows before
# it is even proposed (mirrors CAPITAL_SAFETY.md acceptance).
MAX_PEAK_DEPLOY_PCT = 62.0
MAX_DD_PCT = 12.0


def run(cmd, **kw):
    print(f"  $ {' '.join(str(c) for c in cmd)}", flush=True)
    return subprocess.run(cmd, cwd=USER_DATA.parent, **kw)


def refresh_win_model():
    print("[1/3] refreshing deal dataset + win-probability model ...")
    run([sys.executable, str(SCRIPTS / "build_deal_dataset.py")], check=False)
    run([sys.executable, str(SCRIPTS / "win_probability_model.py")], check=False)


def maybe_search(n: int):
    if n <= 0:
        return
    if not VENV_PY.exists():
        print(f"  (skip search: venv not found at {VENV_PY})")
        return
    print(f"[opt] running {n} Optuna train-search trials + validating top 5 ...")
    run([str(VENV_PY), str(SCRIPTS / "run_optuna.py"), "--trials", str(n)], check=False)
    run([str(VENV_PY), str(SCRIPTS / "run_optuna.py"), "--validate", "5"], check=False)


def pick_candidate():
    print("[2/3] selecting best safe out-of-sample candidate ...")
    if not VALIDATION.exists():
        print(f"  no {VALIDATION.name}; run run_optuna.py --validate first "
              f"(or pass --search N). Nothing to propose.")
        return None
    report = json.loads(VALIDATION.read_text())
    safe = []
    for e in report:
        v = e.get("validate")
        if not v:
            continue
        if v["peak_deploy_pct"] <= MAX_PEAK_DEPLOY_PCT and v["dd_pct"] <= MAX_DD_PCT:
            safe.append(e)
    if not safe:
        print("  no validated trial passed the safety gates - NO candidate "
              "proposed (correct outcome; don't relax the gates to force one).")
        return None
    best = max(safe, key=lambda e: e["validate"]["obj"])
    print(f"  chose trial {best['trial']}: validate obj {best['validate']['obj']}, "
          f"peak {best['validate']['peak_deploy_pct']}%, dd {best['validate']['dd_pct']}%")
    return best


def emit_candidate(best):
    print("[3/3] writing inert candidate + gate checklist ...")
    live = json.loads(LIVE_CONFIG.read_text()).get("wave_rider", {})
    params = best["params"]
    diff = {k: {"live": live.get(k), "candidate": v}
            for k, v in params.items() if live.get(k) != v}
    CAND_DIR.mkdir(parents=True, exist_ok=True)
    date = datetime.now(timezone.utc).strftime("%Y%m%d")
    out = CAND_DIR / f"{date}_candidate.json"
    out.write_text(json.dumps({
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "source_trial": best["trial"],
        "validate_metrics": best["validate"],
        "candidate_wave_rider_params": params,
        "diff_vs_live": diff,
        "STATUS": "PROPOSAL ONLY - not applied. config.json is untouched.",
        "deploy_gate_checklist": [
            "1. Review diff_vs_live below - understand every changed knob.",
            "2. python user_data/scripts/test_sidecar.py MUST pass.",
            "3. Re-confirm validate_metrics: peak_deploy <=62%, dd <=12%.",
            "4. Snapshot current WaveRiderDCA.py + config.json to Code Backups/.",
            "5. Manually apply the diff to config.json (a human edit).",
            "6. docker compose restart freqtrade; watch first cycle for errors.",
        ],
    }, indent=2))
    print(f"  wrote {out}")
    if diff:
        print("  proposed changes vs live:")
        for k, d in diff.items():
            print(f"    {k}: {d['live']} -> {d['candidate']}")
    else:
        print("  candidate is IDENTICAL to live config - no change proposed.")
    print("\n  REMINDER: this is a proposal. config.json was NOT modified.")


def main():
    n = 0
    if "--search" in sys.argv:
        n = int(sys.argv[sys.argv.index("--search") + 1])
    refresh_win_model()
    maybe_search(n)
    best = pick_candidate()
    if best:
        emit_candidate(best)
    print("\nrelearn cycle done (offline; nothing deployed).")


if __name__ == "__main__":
    main()
