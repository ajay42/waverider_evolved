"""
Flatten every backtest result zip into one row per closed trade, enriched
with as-of wave stats, for the win-probability model (win_probability_model.py).

Reads:  backtest_results/{matrix,tail,stage2}/*.zip   (53 zips at build time)
        cohorts/*_wave*.json  +  *_volume.json        (per-pair wave stats)
Writes: analysis/deal_outcomes.csv

Wave-stat enrichment is AS-OF and lookahead-free: each trade is joined to the
newest cohort whose `asof` date is <= the trade's open date, so the wave
score/amplitude/period attached are what the selector would have seen when the
deal opened - never future information. Where a pair isn't in any prior cohort
(e.g. a coin traded in a window we never built a cohort for) the wave columns
are left blank; the model treats those as a missing-data bucket rather than
guessing.

Stdlib only - no pandas/numpy needed to build the table.
"""

import csv
import glob
import json
import zipfile
from datetime import datetime
from pathlib import Path

USER_DATA = Path(__file__).resolve().parents[1]
RESULT_DIRS = ["matrix", "tail", "stage2"]
OUT = USER_DATA / "analysis" / "deal_outcomes.csv"

# exit_reason -> coarse terminal-phase bucket. NOTE (documented caveat):
# grid_close/grid_full_close are AMBIGUOUS - lifecycle-grid, coin-brake and
# crash-freeze all exit through the same grid path, so this bucket blends
# "overstayed" with "governor-braked". Read phase attribution with that in mind.
PHASE_BUCKET = {
    "grace_full_close": "grace",
    "skim_close": "wave_ride",
    "skim_full_close": "wave_ride",
    "grid_close": "grid_or_governor",
    "grid_full_close": "grid_or_governor",
    "phase_d_close": "phase_d",
    "drain_close": "drained",
    "force_exit": "forced",
}


def load_cohort_index() -> list[tuple[datetime, dict]]:
    """
    Return [(asof_datetime, {pair: {wave_score, amplitude, period_h}}), ...]
    sorted oldest-first, merging all cohort variants sharing an asof date.
    """
    by_asof: dict[str, dict] = {}
    for path in glob.glob(str(USER_DATA / "cohorts" / "*.json")):
        d = json.loads(Path(path).read_text())
        asof = d.get("asof")
        if not asof:
            continue
        bucket = by_asof.setdefault(asof, {})
        for row in d.get("detail", []):
            # first writer wins per pair within an asof; variants agree on stats
            bucket.setdefault(row["pair"], {
                "wave_score": row.get("wave_score"),
                "amplitude": row.get("amplitude"),
                "period_h": row.get("period_h"),
            })
    index = [(datetime.fromisoformat(a), b) for a, b in by_asof.items()]
    index.sort(key=lambda x: x[0])
    return index


def wave_stats_asof(index, pair: str, open_dt: datetime) -> dict:
    """Newest cohort with asof <= open_dt that contains `pair` (no lookahead)."""
    found = {}
    for asof_dt, bucket in index:
        if asof_dt <= open_dt and pair in bucket:
            found = bucket[pair]  # keep overwriting -> ends on the newest valid
    return found


def parse_zip(path: Path):
    with zipfile.ZipFile(path) as z:
        name = [n for n in z.namelist()
                if n.endswith(".json") and "meta" not in n and "config" not in n][0]
        data = json.loads(z.read(name))
    res = list(data["strategy"].values())[0]
    return res["trades"]


def main():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    index = load_cohort_index()

    rows = []
    zips = []
    for sub in RESULT_DIRS:
        zips += sorted(glob.glob(str(USER_DATA / "backtest_results" / sub / "*.zip")))

    for zp in zips:
        run_dir = Path(zp).parent.name
        run_id = Path(zp).stem
        try:
            trades = parse_zip(Path(zp))
        except Exception as exc:
            print(f"skip {run_dir}/{run_id}: {exc}")
            continue
        for t in trades:
            open_dt = datetime.fromisoformat(t["open_date"])
            dur_h = (t.get("trade_duration") or 0) / 60.0
            n_buys = sum(1 for o in t.get("orders", []) if o.get("ft_is_entry"))
            open_rate = t.get("open_rate") or 0.0
            min_rate = t.get("min_rate") or open_rate
            price_dd = (open_rate - min_rate) / open_rate * 100.0 if open_rate else 0.0
            ws = wave_stats_asof(index, t["pair"], open_dt)
            period_h = ws.get("period_h")
            rows.append({
                "run_dir": run_dir,
                "run_id": run_id,
                "pair": t["pair"],
                "open_date": t["open_date"],
                "duration_h": round(dur_h, 3),
                "exit_reason": t["exit_reason"],
                "phase_bucket": PHASE_BUCKET.get(t["exit_reason"], "other"),
                "profit_abs": round(t.get("profit_abs", 0.0), 6),
                "profit_ratio": round(t.get("profit_ratio", 0.0), 6),
                "win": 1 if t.get("profit_abs", 0.0) > 0 else 0,
                "n_buy_orders": n_buys,
                "price_dd_pct": round(price_dd, 3),
                "wave_score": round(ws["wave_score"], 4) if ws.get("wave_score") is not None else "",
                "amplitude": round(ws["amplitude"], 4) if ws.get("amplitude") is not None else "",
                "period_h": round(period_h, 3) if period_h is not None else "",
                "wave_age": round(dur_h / period_h, 3) if period_h else "",
            })

    if not rows:
        print("no trades found - are the result zips present?")
        return
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    enriched = sum(1 for r in rows if r["wave_score"] != "")
    wins = sum(r["win"] for r in rows)
    print(f"wrote {OUT}")
    print(f"  {len(rows)} trades from {len(zips)} zips across {RESULT_DIRS}")
    print(f"  {enriched} ({100*enriched/len(rows):.0f}%) enriched with as-of wave stats")
    print(f"  overall win rate: {100*wins/len(rows):.1f}%")


if __name__ == "__main__":
    main()
