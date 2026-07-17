"""
Build static backtest cohorts AS OF a historical date - no lookahead.

For a given date this script scores the (current) Binance USDT universe
using only candles that END at that date, then writes two static pairlists:

  * WAVE cohort   - what the live selector would have picked: choppiness
                    filter + amplitude x (1 - trendiness) ranking.
  * VOLUME cohort - control group: plain top-N by median daily volume.
                    Backtesting both answers "does the selector add value?"

Known limitation (documented in DESIGN.md): the universe is today's listing
set, so coins delisted since then are missing (survivorship bias). Fine for
comparing STRATEGY variants; treat absolute cohort returns with care.

Usage:
    python build_cohorts.py --date 20260302
Output:
    user_data/cohorts/<date>_wave.json / <date>_volume.json (+ console table)
"""

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from pairlist_updater import (USER_DATA, http_json, load_settings, log,
                              score_symbol, tradable_usdt_pairs, BINANCE)

COHORT_DIR = USER_DATA / "cohorts"

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def old_enough_asof(symbol: str, min_days: int, end_ms: int) -> bool:
    url = (f"{BINANCE}/api/v3/klines?symbol={symbol}&interval=1d"
           f"&limit={min_days + 1}&endTime={end_ms}")
    return len(http_json(url)) >= min_days + 1


def main():
    if "--date" not in sys.argv:
        print("usage: python build_cohorts.py --date YYYYMMDD")
        return
    date_str = sys.argv[sys.argv.index("--date") + 1]
    asof = datetime.strptime(date_str, "%Y%m%d").replace(tzinfo=timezone.utc)
    end_ms = int(asof.timestamp() * 1000)

    settings = load_settings()
    n = settings["max_coins"]
    pairs = tradable_usdt_pairs()
    log(f"scoring {len(pairs)} symbols as of {asof.date()} (one klines call each)")

    rows = []
    for i, (symbol, pair) in enumerate(sorted(pairs.items())):
        try:
            amplitude, median_daily, trendiness, period = score_symbol(
                symbol, settings, end_ms=end_ms)
        except Exception as exc:
            log(f"score failed for {symbol}: {exc}")
            continue
        if median_daily < settings["min_median_daily_volume_usd"]:
            continue
        rows.append({
            "pair": pair, "symbol": symbol, "amplitude": amplitude,
            "trendiness": trendiness, "median_daily": median_daily,
            "wave_score": amplitude * (1 - trendiness), "period_h": period,
        })
        time.sleep(0.12)
        if (i + 1) % 100 == 0:
            log(f"...{i + 1}/{len(pairs)} scored, {len(rows)} candidates so far")

    # WAVE cohort: the live selector's rules, applied as-of
    wave_pool = [r for r in rows if r["trendiness"] <= settings["max_trendiness"]]
    wave_pool.sort(key=lambda r: r["wave_score"], reverse=True)
    wave_cohort = []
    for r in wave_pool:
        if len(wave_cohort) >= n:
            break
        try:
            if settings["use_age_filter"] and not old_enough_asof(
                    r["symbol"], settings["min_listing_age_days"], end_ms):
                continue
        except Exception:
            continue
        time.sleep(0.12)
        wave_cohort.append(r)

    # VOLUME cohort (control): plain liquidity ranking, no wave logic
    volume_pool = sorted(rows, key=lambda r: r["median_daily"], reverse=True)
    volume_cohort = volume_pool[:n]

    COHORT_DIR.mkdir(exist_ok=True)
    for name, cohort in (("wave", wave_cohort), ("volume", volume_cohort)):
        out = COHORT_DIR / f"{date_str}_{name}.json"
        out.write_text(json.dumps({
            "asof": asof.isoformat(),
            "cohort": name,
            "pairs": [r["pair"] for r in cohort],
            "detail": cohort,
        }, indent=2))
        print(f"\n{name.upper()} cohort ({out}):")
        for r in cohort:
            print(f"  {r['pair']:<14} score {r['wave_score']:6.2f}  "
                  f"amp {r['amplitude']:5.2f}%  trend {r['trendiness']:4.2f}  "
                  f"medvol ${r['median_daily'] / 1e6:6.1f}M")


if __name__ == "__main__":
    main()
