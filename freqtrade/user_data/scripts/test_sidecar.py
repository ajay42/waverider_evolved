"""
Regression tests for the sidecar's decision math. Run after ANY edit to
pairlist_updater.py:

    python user_data/scripts/test_sidecar.py

Born from a real bug (2026-07-15): a patch extending read_deal_counts
dropped the closed-trades branch, silently zeroing every coin's earnings -
the profit-drain then evicted a profitable coin (SENT). These tests make
that class of slip loud instead of silent.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pairlist_updater import (_closes_since, capitulated_since,
                              closed_runs_since, realized_profit_since)

FAKE_DEALS = {
    "GOOD/USDT": {
        "open": 1,
        "open_trades": [{"id": 9, "open_date": "2026-07-15 06:31:00",
                         "stake": 10.0, "braked": False}],
        "closes": [
            ("2026-07-15 06:27:10.300000", 0.39, "grace_full_close"),
            ("2026-07-14 10:00:00", 0.20, "skim_full_close"),  # pre-join!
        ],
    },
    "CAPIT/USDT": {
        "open": 0, "open_trades": [],
        "closes": [("2026-07-15 12:00:00", -5.0, "phase_d_close")],
    },
    "EMPTY/USDT": {"open": 1, "open_trades": [], "closes": []},
}
JOINED = "2026-07-14T14:34:26+00:00"


def run():
    checks = 0

    # closes since join must include post-join, exclude pre-join
    since = _closes_since(FAKE_DEALS, "GOOD/USDT", JOINED)
    assert len(since) == 1, f"expected 1 close since join, got {len(since)}"
    checks += 1

    # realized profit: only the post-join close counts
    realized = realized_profit_since(FAKE_DEALS, "GOOD/USDT", JOINED)
    assert abs(realized - 0.39) < 1e-9, f"realized wrong: {realized}"
    checks += 1

    # run counting matches
    assert closed_runs_since(FAKE_DEALS, "GOOD/USDT", JOINED) == 1
    checks += 1

    # capitulation detection
    assert capitulated_since(FAKE_DEALS, "CAPIT/USDT", JOINED) is True
    assert capitulated_since(FAKE_DEALS, "GOOD/USDT", JOINED) is False
    checks += 1

    # empty/missing pairs are safe
    assert realized_profit_since(FAKE_DEALS, "EMPTY/USDT", JOINED) == 0
    assert realized_profit_since(FAKE_DEALS, "MISSING/USDT", JOINED) == 0
    checks += 1

    print(f"OK - {checks} sidecar decision-math checks passed")


if __name__ == "__main__":
    run()


# ---- scoring-math unit tests (synthetic candles with KNOWN answers) ----

def _mk_klines(closes, highs=None, lows=None, vol=1_000_000.0):
    """Build fake 4h klines: [open_ms, open, high, low, close, ?, close_ms, quote_vol]"""
    out = []
    for i, c in enumerate(closes):
        hi = highs[i] if highs else c * 1.01
        lo = lows[i] if lows else c * 0.99
        out.append([i, c, hi, lo, c, 0, i, vol])
    return out


def test_scoring_math():
    import math
    import pairlist_updater as plu
    settings = {"amplitude_interval": "4h", "amplitude_lookback_candles": 42}

    calls = {}
    def fake_http(url):
        return calls["klines"]
    original = plu.http_json
    plu.http_json = fake_http
    try:
        # 1) clean sine wave: trendiness ~ 0, period exact (choose 12-candle
        #    cycle => 48h), amplitude > 0
        closes = [100 + 10 * math.sin(2 * math.pi * i / 12) for i in range(43)]
        calls["klines"] = _mk_klines(closes)
        amp, vol, trend, period = plu.score_symbol("X", settings)
        assert trend < 0.15, f"sine should be untrendy, got {trend}"
        assert 40 <= period <= 56, f"sine period ~48h, got {period}"
        assert amp > 1.0, f"sine amplitude should register, got {amp}"

        # 2) straight ramp: trendiness ~ 1 (pure trend must rank last)
        closes = [100 + i for i in range(43)]
        calls["klines"] = _mk_klines(closes)
        amp, vol, trend, period = plu.score_symbol("X", settings)
        assert trend > 0.95, f"ramp should be maximally trendy, got {trend}"

        # 3) flat line: amplitude ~ 0 (score must be ~0, never negative)
        closes = [100.0] * 43
        calls["klines"] = _mk_klines(closes, highs=[100.0] * 43, lows=[100.0] * 43)
        amp, vol, trend, period = plu.score_symbol("X", settings)
        assert abs(amp) < 0.01, f"flat amplitude should be ~0, got {amp}"

        # 4) too-young coin: sentinel rank-last values
        calls["klines"] = _mk_klines([100.0] * 10)
        amp, vol, trend, period = plu.score_symbol("X", settings)
        assert amp <= -900, "young coin must rank last"

        # 5) median-daily volume math: 42 candles x 6/day, constant 1M quote
        #    per candle => 6M/day median
        closes = [100 + (i % 5) for i in range(43)]
        calls["klines"] = _mk_klines(closes, vol=1_000_000.0)
        amp, vol, trend, period = plu.score_symbol("X", settings)
        assert 5_900_000 <= vol <= 6_100_000, f"median daily vol ~6M, got {vol}"
    finally:
        plu.http_json = original
    print("OK - 5 scoring-math checks passed")


test_scoring_math()
