"""
Empirical win/success-probability model for Wave Rider deals.

Same evidence-first spirit as selector_predictive_power.py: interpretable
conditional win-rate tables first, a small logistic regression second as a
combined-signal cross-check - nothing a human can't audit.

Question it answers: given what we can observe about a deal (its terminal
phase, how deep price went against it, its wave-age, and the coin's wave
score at open), what is its probability of closing profitably? The intended
downstream use is informing Phase-D capitulation timing (close vs extend) -
but this script only BUILDS and VALIDATES the model; wiring it into the live
strategy is a separate, separately-reviewed step and is NOT done here.

Walk-forward discipline (same as the rest of the project): FIT on the
2021-2022 era, and hold out the 2024-2026 era for calibration - the model is
never scored on data it was fit on.

Reads:  analysis/deal_outcomes.csv   (from build_deal_dataset.py)
Writes: win_probability_model.json   + console report
Stdlib only (a tiny hand-rolled logistic regression - no numpy/sklearn).
"""

import csv
import json
import math
from collections import defaultdict
from datetime import datetime
from pathlib import Path

USER_DATA = Path(__file__).resolve().parents[1]
CSV_IN = USER_DATA / "analysis" / "deal_outcomes.csv"
OUT = USER_DATA / "win_probability_model.json"

TRAIN_MAX_YEAR = 2022      # fit on <= 2022
VALIDATE_MIN_YEAR = 2024   # hold out >= 2024


def load_rows():
    rows = []
    with open(CSV_IN, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            r["year"] = datetime.fromisoformat(r["open_date"]).year
            r["win"] = int(r["win"])
            for k in ("wave_score", "price_dd_pct", "wave_age", "profit_abs"):
                r[k] = float(r[k]) if r[k] not in ("", None) else None
            rows.append(r)
    return rows


def rate_table(rows, keyfn, label):
    """Win-rate + count + avg profit grouped by keyfn(row)."""
    buckets = defaultdict(lambda: {"n": 0, "wins": 0, "pnl": 0.0})
    for r in rows:
        k = keyfn(r)
        if k is None:
            continue
        b = buckets[k]
        b["n"] += 1
        b["wins"] += r["win"]
        b["pnl"] += r["profit_abs"] or 0.0
    out = []
    for k in sorted(buckets, key=lambda x: (isinstance(x, str), x)):
        b = buckets[k]
        out.append({
            "bucket": k,
            "n": b["n"],
            "win_rate": round(100.0 * b["wins"] / b["n"], 2),
            "avg_pnl": round(b["pnl"] / b["n"], 4),
        })
    return {"label": label, "rows": out}


def decile_edges(values, n=10):
    s = sorted(values)
    if not s:
        return []
    return [s[int(i * (len(s) - 1) / n)] for i in range(1, n)]


def bucket_by_edges(v, edges):
    if v is None:
        return None
    for i, e in enumerate(edges):
        if v <= e:
            return i
    return len(edges)


# ---- tiny standardized logistic regression (gradient descent, stdlib) ----

def standardize(rows, feats):
    stats = {}
    for f in feats:
        vals = [r[f] for r in rows if r.get(f) is not None]
        mu = sum(vals) / len(vals) if vals else 0.0
        var = sum((x - mu) ** 2 for x in vals) / len(vals) if vals else 1.0
        sd = math.sqrt(var) or 1.0
        stats[f] = (mu, sd)
    return stats


def featurize(r, feats, stats, phases):
    x = [1.0]  # bias
    for f in feats:
        mu, sd = stats[f]
        v = r.get(f)
        x.append(((v - mu) / sd) if v is not None else 0.0)
    for p in phases:  # phase one-hots (drop-one not needed; bias absorbs)
        x.append(1.0 if r["phase_bucket"] == p else 0.0)
    return x


def sigmoid(z):
    if z < -35:
        return 1e-15
    if z > 35:
        return 1.0 - 1e-15
    return 1.0 / (1.0 + math.exp(-z))


def train_logit(train, feats, stats, phases, iters=400, lr=0.3, l2=1e-3):
    dim = 1 + len(feats) + len(phases)
    w = [0.0] * dim
    n = len(train)
    X = [featurize(r, feats, stats, phases) for r in train]
    y = [r["win"] for r in train]
    for _ in range(iters):
        grad = [0.0] * dim
        for xi, yi in zip(X, y):
            p = sigmoid(sum(wj * xj for wj, xj in zip(w, xi)))
            err = p - yi
            for j in range(dim):
                grad[j] += err * xi[j]
        for j in range(dim):
            w[j] -= lr * (grad[j] / n + l2 * w[j])
    return w


def brier_and_calib(rows, w, feats, stats, phases):
    X = [featurize(r, feats, stats, phases) for r in rows]
    preds = [sigmoid(sum(wj * xj for wj, xj in zip(w, xi))) for xi in X]
    y = [r["win"] for r in rows]
    brier = sum((p - t) ** 2 for p, t in zip(preds, y)) / len(y)
    # 5-bin calibration
    bins = defaultdict(lambda: {"n": 0, "pred": 0.0, "act": 0})
    for p, t in zip(preds, y):
        b = min(4, int(p * 5))
        bins[b]["n"] += 1
        bins[b]["pred"] += p
        bins[b]["act"] += t
    calib = []
    for b in sorted(bins):
        d = bins[b]
        calib.append({
            "bin": f"{b*20}-{b*20+20}%",
            "n": d["n"],
            "mean_pred": round(100 * d["pred"] / d["n"], 1),
            "actual": round(100 * d["act"] / d["n"], 1),
        })
    return round(brier, 5), calib


def print_table(tab):
    print(f"\n-- {tab['label']} --")
    print(f"{'bucket':<20} {'n':>7} {'win%':>7} {'avgPnL$':>9}")
    for r in tab["rows"]:
        print(f"{str(r['bucket']):<20} {r['n']:>7} {r['win_rate']:>7.2f} {r['avg_pnl']:>9.4f}")


def main():
    rows = load_rows()
    train = [r for r in rows if r["year"] <= TRAIN_MAX_YEAR]
    valid = [r for r in rows if r["year"] >= VALIDATE_MIN_YEAR]
    print(f"loaded {len(rows)} trades | train(<= {TRAIN_MAX_YEAR}) {len(train)} | "
          f"validate(>= {VALIDATE_MIN_YEAR}) {len(valid)}")
    print(f"base win rate: train {100*sum(r['win'] for r in train)/max(1,len(train)):.2f}% | "
          f"validate {100*sum(r['win'] for r in valid)/max(1,len(valid)):.2f}%")

    # ---- interpretable conditional tables (fit on TRAIN) ----
    tables = {}
    tables["by_phase"] = rate_table(train, lambda r: r["phase_bucket"], "Win rate by terminal phase")

    ws_edges = decile_edges([r["wave_score"] for r in train if r["wave_score"] is not None])
    tables["by_wave_score_decile"] = rate_table(
        train, lambda r: bucket_by_edges(r["wave_score"], ws_edges),
        "Win rate by wave-score decile (0=lowest)")

    dd_edges = [1, 3, 6, 10, 15, 25]
    tables["by_drawdown"] = rate_table(
        train, lambda r: bucket_by_edges(r["price_dd_pct"], dd_edges),
        f"Win rate by price-drawdown bucket (edges {dd_edges}%)")

    age_edges = [1, 3, 6, 12, 18]
    tables["by_wave_age"] = rate_table(
        train, lambda r: bucket_by_edges(r["wave_age"], age_edges),
        f"Win rate by wave-age bucket (edges {age_edges} waves)")

    for t in tables.values():
        print_table(t)

    # ---- logistic regression cross-check ----
    feats = ["wave_score", "price_dd_pct", "wave_age"]
    phases = sorted({r["phase_bucket"] for r in train})
    # rows usable for the model need the numeric feats present
    tr = [r for r in train if all(r.get(f) is not None for f in feats)]
    va = [r for r in valid if all(r.get(f) is not None for f in feats)]
    stats = standardize(tr, feats)
    w = train_logit(tr, feats, stats, phases)
    tr_brier, _ = brier_and_calib(tr, w, feats, stats, phases)
    va_brier, va_calib = brier_and_calib(va, w, feats, stats, phases) if va else (None, [])

    coef = {"bias": round(w[0], 4)}
    for i, f in enumerate(feats):
        coef[f] = round(w[1 + i], 4)
    for j, p in enumerate(phases):
        coef[f"phase={p}"] = round(w[1 + len(feats) + j], 4)

    print("\n-- logistic regression (standardized coefficients) --")
    for k, v in coef.items():
        print(f"  {k:<24} {v:+.4f}")
    print(f"\nBrier score  train {tr_brier}  |  validate(held-out) {va_brier}  "
          f"(lower=better; base-rate model ~ {round(_baseline_brier(tr),5)})")
    if va_calib:
        print("\n-- calibration on held-out era (predicted vs actual win%) --")
        print(f"{'pred-bin':<12} {'n':>7} {'meanPred%':>10} {'actual%':>9}")
        for c in va_calib:
            print(f"{c['bin']:<12} {c['n']:>7} {c['mean_pred']:>10.1f} {c['actual']:>9.1f}")

    OUT.write_text(json.dumps({
        "n_train": len(tr), "n_validate": len(va),
        "tables": tables,
        "logit_coefficients": coef,
        "brier_train": tr_brier, "brier_validate": va_brier,
        "validate_calibration": va_calib,
        "notes": "As-of enriched, walk-forward (fit<=2022, validate>=2024). "
                 "grid_or_governor phase bucket is ambiguous (lifecycle/brake/"
                 "freeze share the grid exit). Not wired to live decisions.",
    }, indent=2))
    print(f"\nwrote {OUT}")


def _baseline_brier(rows):
    p = sum(r["win"] for r in rows) / len(rows)
    return sum((p - r["win"]) ** 2 for r in rows) / len(rows)


if __name__ == "__main__":
    main()
