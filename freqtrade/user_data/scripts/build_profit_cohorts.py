"""
Profit-lever #3: build "WAVEUP" cohorts - coins that WAVE and drift gently UP.

The live selector scores amplitude x (1 - trendiness): pure chop preference,
direction-blind. Thesis to test: skims come easier when the chop rides a mild
updrift (the tide helps every combo reach TP), while a waving-but-sinking coin
fights the tide. So: same wave scoring, then a SIGNED 7-day drift factor:

    drift > +25%      x0.85   (pumpy - trend risk, selector's weak spot)
    +2% .. +25%       x1.20   (sweet spot: waves + gentle updrift)
    -5% .. +2%        x1.00   (neutral chop - current live behavior)
    < -5%             x0.80   (waving but sinking)

As-of correct: all metrics from candles ENDING at --date (no lookahead),
same 4h x 42 window as the live selector. This script deliberately does NOT
import from or modify pairlist_updater.py - that file drives the LIVE bot.
The small scoring math is duplicated here (noted, accepted) so live code
stays untouched during profit R&D.

Usage:  python build_profit_cohorts.py --date 20220613
Output: user_data/cohorts/<date>_waveup.json
"""

import json
import statistics
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

USER_DATA = Path(__file__).resolve().parents[1]
COHORT_DIR = USER_DATA / "cohorts"
BINANCE = "https://api.binance.com"

# mirror of live selector settings (pairlist_settings in config)
INTERVAL, LOOKBACK = "4h", 42          # one week of 4h candles
MIN_MEDIAN_DAILY = 3_000_000           # $3M median-daily floor
MAX_TRENDINESS = 0.4
N_COINS = 10

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def http_json(url):
    with urllib.request.urlopen(url, timeout=15) as r:
        return json.loads(r.read().decode())


def tradable_usdt_pairs():
    info = http_json(f"{BINANCE}/api/v3/exchangeInfo")
    out = {}
    for s in info["symbols"]:
        if (s["quoteAsset"] == "USDT" and s["status"] == "TRADING"
                and s["isSpotTradingAllowed"]):
            out[s["symbol"]] = f"{s['baseAsset']}/USDT"
    return out


def drift_factor(drift_pct: float) -> float:
    if drift_pct > 25:
        return 0.85
    if drift_pct > 2:
        return 1.20
    if drift_pct >= -5:
        return 1.00
    return 0.80


def score_with_drift(symbol: str, end_ms: int):
    """One klines fetch -> (amplitude%, median_daily_vol, trendiness,
    period_h, drift_pct). Same math as the live selector + signed drift."""
    url = (f"{BINANCE}/api/v3/klines?symbol={symbol}&interval={INTERVAL}"
           f"&limit={LOOKBACK + 1}&endTime={end_ms}")
    klines = http_json(url)
    complete = klines[:-1]
    if len(complete) < LOOKBACK:
        return None
    closes = [float(k[4]) for k in complete]
    swings, day_vols = [], {}
    path = 0.0
    for i, k in enumerate(complete):
        high, low = float(k[2]), float(k[3])
        mid = (high + low) / 2
        if mid > 0:
            swings.append((high - low) / mid * 100)
        day = int(k[0] // 86_400_000)
        day_vols[day] = day_vols.get(day, 0.0) + float(k[7])  # quote volume
        if i > 0:
            path += abs(closes[i] - closes[i - 1])
    amplitude = sum(swings) / len(swings)
    net = closes[-1] - closes[0]
    trendiness = (abs(net) / path) if path > 0 else 1.0
    drift_pct = net / closes[0] * 100 if closes[0] > 0 else 0.0
    median_daily = statistics.median(day_vols.values()) if day_vols else 0.0
    # wave period from direction changes (two changes = one wave)
    changes = 0
    for i in range(2, len(closes)):
        if (closes[i] - closes[i - 1]) * (closes[i - 1] - closes[i - 2]) < 0:
            changes += 1
    waves = max(changes / 2.0, 0.5)
    period_h = (len(closes) * 4.0) / waves
    return amplitude, median_daily, trendiness, period_h, drift_pct


def main():
    date_str = sys.argv[sys.argv.index("--date") + 1]
    asof = datetime.strptime(date_str, "%Y%m%d").replace(tzinfo=timezone.utc)
    end_ms = int(asof.timestamp() * 1000)
    pairs = tradable_usdt_pairs()
    print(f"[waveup] scoring {len(pairs)} symbols as of {asof.date()}")

    rows = []
    for i, (symbol, pair) in enumerate(sorted(pairs.items())):
        try:
            r = score_with_drift(symbol, end_ms)
        except Exception:
            continue
        if r is None:
            continue
        amplitude, median_daily, trendiness, period_h, drift = r
        if median_daily < MIN_MEDIAN_DAILY or trendiness > MAX_TRENDINESS:
            continue
        base = amplitude * (1 - trendiness)
        rows.append({
            "pair": pair, "symbol": symbol, "amplitude": amplitude,
            "trendiness": trendiness, "median_daily": median_daily,
            "period_h": period_h, "drift_pct": round(drift, 2),
            "wave_score": base,                      # keep for comparability
            "waveup_score": base * drift_factor(drift),
        })
        time.sleep(0.12)
        if (i + 1) % 100 == 0:
            print(f"  ...{i + 1}/{len(pairs)}, {len(rows)} candidates")

    rows.sort(key=lambda r: r["waveup_score"], reverse=True)
    cohort = rows[:N_COINS]
    out = COHORT_DIR / f"{date_str}_waveup.json"
    out.write_text(json.dumps({
        "asof": asof.isoformat(), "cohort": "waveup",
        "pairs": [r["pair"] for r in cohort], "detail": cohort,
    }, indent=2))
    print(f"\nWAVEUP cohort -> {out}")
    for r in cohort:
        print(f"  {r['pair']:<14} up-score {r['waveup_score']:6.2f} "
              f"(base {r['wave_score']:5.2f}, drift {r['drift_pct']:+6.1f}%)")


if __name__ == "__main__":
    main()
