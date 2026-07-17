"""
Walk-forward Optuna optimizer for Wave Rider (host-side, capital-safety-first).

Freqtrade's native `hyperopt` can only optimize over one continuous timerange,
so it cannot enforce train-on-one-regime / validate-on-another. This custom
loop does: each Optuna trial is scored ONLY on the TRAIN windows; the held-out
VALIDATE windows are never seen during search. After the search, run
`--validate` to grade the best trials out-of-sample - a candidate is only
trustworthy if it survives that.

Reuses (does not reimplement):
  - run_stage2.run_one / TRAIN_WINDOWS / VALIDATE_WINDOWS / SAFETY_BASE
  - analyze_tail.parse_run  (peak-deployment event sweep + dd% + profit%)

Objective (MAXIMIZE) is capital-safety-first, mirroring CAPITAL_SAFETY.md's
acceptance test - profit is penalized hard for breaching the deployment
ceiling or the drawdown tolerance, so the optimizer cannot buy return with
tail risk:

    score = mean_profit_pct
            - LAMBDA_DEPLOY * max(0, peak_deploy_pct - DEPLOY_CEILING)
            - LAMBDA_DD     * max(0, dd_pct - DD_TOLERANCE)

Requires the host venv with optuna:  freqtrade/.venv-tools/
Run (train search):     .venv-tools/Scripts/python user_data/scripts/run_optuna.py --trials 16
Run (validate best K):  .venv-tools/Scripts/python user_data/scripts/run_optuna.py --validate 5
"""

import argparse
import json
import sys
from pathlib import Path

import optuna

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_stage2 import run_one, TRAIN_WINDOWS, VALIDATE_WINDOWS, SAFETY_BASE  # noqa: E402
from analyze_tail import parse_run  # noqa: E402

USER_DATA = Path(__file__).resolve().parents[1]
STUDY_DIR = USER_DATA / "optuna_studies"
RESULTS_DIR = USER_DATA / "backtest_results" / "optuna"
STUDY_NAME = "geometry_governor"

# Objective weights. Deployment above 60% and drawdown above tolerance are
# penalized steeply - a config cannot win by taking tail risk.
DEPLOY_CEILING = 60.0
DD_TOLERANCE = 10.0
LAMBDA_DEPLOY = 0.5     # score points lost per % of deployment over ceiling
LAMBDA_DD = 1.0         # score points lost per % of drawdown over tolerance

# Which cohort each window uses (matches run_stage2's "wave" cohorts).
TRAIN_COHORT_KIND = "wave"


def _cohort_pairs(date: str, kind: str) -> list:
    return json.loads((USER_DATA / "cohorts" / f"{date}_{kind}.json").read_text())["pairs"]


def _params_from_trial(trial: optuna.Trial) -> dict:
    p = {
        "safety_order_price_deviation_perc": round(trial.suggest_float("dev", 0.5, 3.0, step=0.1), 2),
        "safety_order_volume_scale": round(trial.suggest_float("vol", 1.02, 1.20, step=0.01), 2),
        "coin_brake_wave_mult": round(trial.suggest_float("brake_mult", 1.2, 3.0, step=0.1), 2),
        "coin_brake_floor_perc": round(trial.suggest_float("brake_floor", 8.0, 20.0, step=1.0), 1),
        "max_aggregate_exposure_pct": int(trial.suggest_int("agg_ceiling", 40, 80, step=5)),
        "min_active_wave_score": round(trial.suggest_float("quality_floor", 1.0, 3.0, step=0.1), 2),
    }
    if trial.suggest_categorical("dynamic_ladder", [False, True]):
        p["dynamic_ladder_enabled"] = True
        p["dynamic_spacing_mult"] = round(trial.suggest_float("dyn_spacing", 0.3, 0.8, step=0.05), 2)
        p["dynamic_tp_mult"] = round(trial.suggest_float("dyn_tp", 0.3, 0.8, step=0.05), 2)
    return p


def _score_windows(windows: dict, params: dict, tag: str) -> dict:
    """Run each window with these overrides; return aggregated safety metrics."""
    profits, peaks, dds = [], [], []
    for date, (label, timerange) in windows.items():
        pairs = _cohort_pairs(date, TRAIN_COHORT_KIND)
        run_id = f"opt_{tag}_{label}"
        ok = run_one(run_id, timerange, pairs, params, RESULTS_DIR)
        if not ok:
            return {"ok": False}
        m = parse_run(RESULTS_DIR / f"{run_id}.zip")
        profits.append(m["profit_pct"])
        peaks.append(m["peak_deploy_pct"])
        dds.append(m["dd_pct"])
    return {
        "ok": True,
        "mean_profit_pct": sum(profits) / len(profits),
        "peak_deploy_pct": max(peaks),      # worst-case across windows
        "dd_pct": max(dds),
    }


def objective_value(m: dict) -> float:
    return (m["mean_profit_pct"]
            - LAMBDA_DEPLOY * max(0.0, m["peak_deploy_pct"] - DEPLOY_CEILING)
            - LAMBDA_DD * max(0.0, m["dd_pct"] - DD_TOLERANCE))


def make_objective():
    def objective(trial: optuna.Trial) -> float:
        params = {**SAFETY_BASE, **_params_from_trial(trial)}
        m = _score_windows(TRAIN_WINDOWS, params, f"t{trial.number}")
        if not m["ok"]:
            raise optuna.TrialPruned()  # a failed backtest is not a data point
        trial.set_user_attr("mean_profit_pct", round(m["mean_profit_pct"], 3))
        trial.set_user_attr("peak_deploy_pct", round(m["peak_deploy_pct"], 2))
        trial.set_user_attr("dd_pct", round(m["dd_pct"], 2))
        trial.set_user_attr("params", params)
        return objective_value(m)
    return objective


def get_study() -> optuna.Study:
    STUDY_DIR.mkdir(parents=True, exist_ok=True)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    return optuna.create_study(
        study_name=STUDY_NAME,
        storage=f"sqlite:///{(STUDY_DIR / (STUDY_NAME + '.db')).as_posix()}",
        direction="maximize",
        load_if_exists=True,
        sampler=optuna.samplers.TPESampler(seed=42),
    )


def cmd_search(n_trials: int):
    study = get_study()
    print(f"[optuna] study '{STUDY_NAME}' has {len(study.trials)} trials; "
          f"running {n_trials} more. TRAIN windows only (walk-forward).")
    study.optimize(make_objective(), n_trials=n_trials)
    print(f"[optuna] done. best value {study.best_value:.3f}")
    print(f"[optuna] best params: {json.dumps(study.best_trial.user_attrs.get('params'), indent=2)}")


def cmd_validate(top_k: int):
    """Grade the best TRAIN trials on the held-out VALIDATE windows."""
    study = get_study()
    complete = [t for t in study.trials if t.value is not None]
    complete.sort(key=lambda t: t.value, reverse=True)
    top = complete[:top_k]
    print(f"[validate] grading top {len(top)} of {len(complete)} trials on HELD-OUT windows")
    report = []
    for t in top:
        params = t.user_attrs["params"]
        m = _score_windows(VALIDATE_WINDOWS, params, f"v{t.number}")
        entry = {
            "trial": t.number,
            "train_score": round(t.value, 3),
            "train": {k: t.user_attrs[k] for k in ("mean_profit_pct", "peak_deploy_pct", "dd_pct")},
            "validate": None if not m["ok"] else {
                "mean_profit_pct": round(m["mean_profit_pct"], 3),
                "peak_deploy_pct": round(m["peak_deploy_pct"], 2),
                "dd_pct": round(m["dd_pct"], 2),
                "obj": round(objective_value(m), 3),
            },
            "params": params,
        }
        report.append(entry)
        v = entry["validate"]
        print(f"  trial {t.number}: train {entry['train']} -> validate {v}")
    out = USER_DATA / "optuna_validation.json"
    out.write_text(json.dumps(report, indent=2))
    print(f"[validate] wrote {out}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trials", type=int, default=0, help="run N train-search trials")
    ap.add_argument("--validate", type=int, default=0, help="grade top-K trials on held-out windows")
    args = ap.parse_args()
    if args.validate:
        cmd_validate(args.validate)
    else:
        cmd_search(args.trials or 16)


if __name__ == "__main__":
    main()
