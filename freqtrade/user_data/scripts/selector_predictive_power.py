"""
Selector soundness - the decisive test: does the wave score PREDICT the
future, or only describe the past?

For a series of historical dates (default: every 2 weeks over the past 12
months), score the whole Binance USDT universe AS OF that date (same
formula, no lookahead), then measure each coin's FORWARD week: how many
skimmable waves (4h swing >= threshold) it actually produced. If the score
works, high-score deciles must show more forward waves than low deciles.

Outputs a decile table + Spearman rank correlation per date and pooled.

Usage (host):
    python user_data/scripts/selector_predictive_power.py [--dates 26] [--step-days 14]
"""

import json
import statistics
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pairlist_updater import (BINANCE, http_json, load_settings, log,
                              score_symbol, tradable_usdt_pairs)

USER_DATA = Path(__file__).resolve().parents[1]
OUT_FILE = USER_DATA / "selector_predictive_power.json"

SKIM_THRESHOLD = 2.2  # % swing that covers TP (2%) + round-trip fees


def forward_wave_count(symbol: str, start_ms: int, settings: dict) -> float:
    """Skimmable 4h swings in the week AFTER start_ms."""
    url = (f"{BINANCE}/api/v3/klines?symbol={symbol}&interval=4h"
           f"&startTime={start_ms}&limit=42")
    klines = http_json(url)
    count = 0
    for k in klines:
        hi, lo = float(k[2]), float(k[3])
        mid = (hi + lo) / 2
        if mid > 0 and 100.0 * (hi - lo) / mid >= SKIM_THRESHOLD:
            count += 1
    return count


def spearman(xs: list, ys: list) -> float:
    def ranks(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        for rank, i in enumerate(order):
            r[i] = rank
        return r
    rx, ry = ranks(xs), ranks(ys)
    mx, my = statistics.mean(rx), statistics.mean(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    dx = sum((a - mx) ** 2 for a in rx) ** 0.5
    dy = sum((b - my) ** 2 for b in ry) ** 0.5
    return num / (dx * dy) if dx and dy else 0.0


def main():
    n_dates = int(sys.argv[sys.argv.index("--dates") + 1]) if "--dates" in sys.argv else 26
    step = int(sys.argv[sys.argv.index("--step-days") + 1]) if "--step-days" in sys.argv else 14

    settings = load_settings()
    pairs = tradable_usdt_pairs()
    log(f"predictive-power study: {n_dates} dates x {len(pairs)} symbols")

    now = datetime.now(timezone.utc)
    all_rows = []          # (date, symbol, score, forward_waves)
    per_date_corr = []

    for d in range(n_dates):
        asof = now - timedelta(days=(d + 1) * step + 7)  # leave a full fwd week
        end_ms = int(asof.timestamp() * 1000)
        scores, forwards = [], []
        for i, symbol in enumerate(sorted(pairs)):
            try:
                amp, medvol, trend, _ = score_symbol(symbol, settings, end_ms=end_ms)
                if medvol < settings["min_median_daily_volume_usd"] or amp <= -900:
                    continue
                score = amp * (1 - trend)
                fwd = forward_wave_count(symbol, end_ms, settings)
            except Exception:
                continue
            scores.append(score)
            forwards.append(fwd)
            all_rows.append((asof.date().isoformat(), symbol, round(score, 3), fwd))
            time.sleep(0.1)
        if len(scores) >= 30:
            corr = spearman(scores, forwards)
            per_date_corr.append(corr)
            log(f"{asof.date()} n={len(scores)} spearman={corr:+.3f}")

    # pooled decile table
    rows = sorted(all_rows, key=lambda r: r[2])
    n = len(rows)
    deciles = []
    for k in range(10):
        chunk = rows[k * n // 10:(k + 1) * n // 10]
        if chunk:
            deciles.append({
                "decile": k + 1,
                "avg_score": round(statistics.mean(r[2] for r in chunk), 2),
                "avg_forward_waves": round(statistics.mean(r[3] for r in chunk), 2),
                "n": len(chunk),
            })

    result = {
        "generated": now.isoformat(),
        "dates": n_dates, "step_days": step,
        "skim_threshold_pct": SKIM_THRESHOLD,
        "observations": n,
        "median_date_spearman": round(statistics.median(per_date_corr), 3) if per_date_corr else None,
        "per_date_spearman": [round(c, 3) for c in per_date_corr],
        "deciles": deciles,
    }
    OUT_FILE.write_text(json.dumps(result, indent=2))
    log(f"saved {OUT_FILE}")
    print("\nDECILES (1=lowest score .. 10=highest):")
    for dd in deciles:
        bar = "#" * int(dd["avg_forward_waves"] * 2)
        print(f"  {dd['decile']:>2}  score~{dd['avg_score']:>6}  "
              f"fwd waves {dd['avg_forward_waves']:>5}  {bar}")
    print(f"\nmedian per-date Spearman: {result['median_date_spearman']}")


if __name__ == "__main__":
    main()
