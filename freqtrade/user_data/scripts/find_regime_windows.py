"""
Classify BTC history into bull / bear / chop windows for regime-separated
backtesting (DESIGN.md section 7).

Method (mechanical, no eyeballing):
  * fetch BTC/USDT daily candles,
  * compute the trailing 30-day return for every day,
  * classify each day: bull if > +15%, bear if < -15%, else chop,
  * merge consecutive same-class days into windows and print the ones long
    enough to backtest (>= 21 days), as freqtrade --timerange strings.

Usage:
    python find_regime_windows.py [--since 2024-01-01]
"""

import json
import sys
import urllib.request
from datetime import datetime, timezone

BINANCE = "https://api.binance.com"
LOOKBACK_DAYS = 30
BULL_THRESHOLD = 0.15
BEAR_THRESHOLD = -0.15
MIN_WINDOW_DAYS = 21

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def fetch_daily_closes(since: datetime) -> list:
    """[(date, close)] for BTC/USDT from `since` until now, paginated."""
    out = []
    start_ms = int(since.timestamp() * 1000)
    while True:
        url = (f"{BINANCE}/api/v3/klines?symbol=BTCUSDT&interval=1d"
               f"&startTime={start_ms}&limit=1000")
        with urllib.request.urlopen(url, timeout=30) as resp:
            klines = json.loads(resp.read())
        if not klines:
            break
        for k in klines:
            day = datetime.fromtimestamp(k[0] / 1000, tz=timezone.utc).date()
            out.append((day, float(k[4])))
        if len(klines) < 1000:
            break
        start_ms = klines[-1][6] + 1  # next after last close time
    return out


def main():
    since_arg = "2024-01-01"
    if "--since" in sys.argv:
        since_arg = sys.argv[sys.argv.index("--since") + 1]
    since = datetime.fromisoformat(since_arg).replace(tzinfo=timezone.utc)

    days = fetch_daily_closes(since)
    if len(days) < LOOKBACK_DAYS + MIN_WINDOW_DAYS:
        print("not enough data")
        return

    # classify each day by trailing 30d return
    classified = []
    for i in range(LOOKBACK_DAYS, len(days)):
        ret = days[i][1] / days[i - LOOKBACK_DAYS][1] - 1
        cls = "bull" if ret > BULL_THRESHOLD else ("bear" if ret < BEAR_THRESHOLD else "chop")
        classified.append((days[i][0], cls, ret))

    # merge consecutive same-class days into windows
    windows = []
    start, current_cls = classified[0][0], classified[0][1]
    for i in range(1, len(classified)):
        day, cls, _ = classified[i]
        if cls != current_cls:
            windows.append((start, classified[i - 1][0], current_cls))
            start, current_cls = day, cls
    windows.append((start, classified[-1][0], current_cls))

    print(f"BTC regime windows since {since_arg} "
          f"(trailing {LOOKBACK_DAYS}d return; bull > +{BULL_THRESHOLD:.0%}, "
          f"bear < {BEAR_THRESHOLD:.0%}; windows >= {MIN_WINDOW_DAYS}d):\n")
    print(f"{'class':<6} {'days':>5}  timerange")
    for start, end, cls in windows:
        length = (end - start).days + 1
        if length < MIN_WINDOW_DAYS:
            continue
        timerange = f"{start.strftime('%Y%m%d')}-{end.strftime('%Y%m%d')}"
        print(f"{cls:<6} {length:>5}  --timerange {timerange}")


if __name__ == "__main__":
    main()
