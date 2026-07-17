"""
Generate synthetic OHLCV feather files for the Tier-B governor stress tests.

Tier A (../../wave_rider_dca/run_synthetic_sandbox.py) curated which SHOCK
SHAPES trap capital and wrote wave_rider_dca/synthetic_shortlist.json. This
script re-expresses each shortlisted shape at realistic time resolution
(1-minute candles over ~3 weeks, ~15h waves) so the FULL live system - all
governors, the wave-period lifecycle, the BTC crash-freeze - actually engages
in a real Freqtrade backtest.

Design choices (all deliberate, documented):
  - Uses the SAME synthetic_paths generator as Tier A (one source of truth for
    the shock maths), just with minute-scale tick counts.
  - Writes to a DEDICATED datadir (data/binance_synthetic/) - never touches
    real market data.
  - Uses REAL pair tickers (from the 20220613 wave cohort, which includes
    BTC/USDT) with synthetic prices, so Freqtrade's exchange metadata
    (min-notional, precision) resolves exactly as it does for real pairs.
  - BTC/USDT is kept as the shared market factor so the strategy's
    regime_reference_pair / crash-freeze informative merge works unchanged.
  - Correlated panel: one market shock * per-coin beta (higher-amplitude alts
    fall harder) + small idiosyncratic wobble -> the correlated crash the
    aggregate/freeze governors exist for.

CAVEAT (stated, not hidden): Freqtrade backtesting has no order-book model, so
"liquidity drought" is only APPROXIMATED via widened candle wicks + a raised
fee in run_synthetic.py - it is a proxy, not a true liquidity simulation.

Run with the tooling venv (needs pandas/pyarrow):
    .venv-tools/Scripts/python user_data/scripts/gen_synthetic_data.py
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

USER_DATA = Path(__file__).resolve().parents[1]
REPO = USER_DATA.parents[1]
sys.path.insert(0, str(REPO / "wave_rider_dca"))
from synthetic_paths import make_correlated_panel  # noqa: E402

OUT_DIR = USER_DATA / "data" / "binance_synthetic"
SHORTLIST = REPO / "wave_rider_dca" / "synthetic_shortlist.json"
COHORT = USER_DATA / "cohorts" / "20220613_wave.json"

START = datetime(2023, 1, 2, 0, 0, tzinfo=timezone.utc)  # arbitrary past anchor
DAY = 1440   # minutes
WAVE = 900   # 15h wave period in minutes
WICK = 0.0015  # baseline intra-candle wick as a fraction of the close

# Minute-scale realizations of the catalogue shapes (only shortlisted ones are
# generated). drop/recovery/tail are in MINUTES; wave_period fixed at ~15h.
TIER_B = {
    "flash_80_no_recover":    dict(magnitude_pct=80, drop_ticks=120,      recovery_frac=0.0, recovery_ticks=0,       wave_amp_pct=2,   wave_period_ticks=WAVE, tail_ticks=16*DAY),
    "flash_60_no_recover":    dict(magnitude_pct=60, drop_ticks=120,      recovery_frac=0.0, recovery_ticks=0,       wave_amp_pct=2,   wave_period_ticks=WAVE, tail_ticks=16*DAY),
    "flash_50_then_flatline": dict(magnitude_pct=50, drop_ticks=60,       recovery_frac=0.0, recovery_ticks=0,       wave_amp_pct=1,   wave_period_ticks=WAVE, tail_ticks=18*DAY),
    "smooth_70_no_waves":     dict(magnitude_pct=70, drop_ticks=4*DAY,    recovery_frac=0.0, recovery_ticks=0,       wave_amp_pct=0.3, wave_period_ticks=WAVE, tail_ticks=12*DAY),
    "wavy_90_extreme":        dict(magnitude_pct=90, drop_ticks=5*DAY,    recovery_frac=0.1, recovery_ticks=3*DAY,   wave_amp_pct=6,   wave_period_ticks=WAVE, tail_ticks=6*DAY),
    "double_dip_75":          dict(magnitude_pct=75, drop_ticks=2*DAY,    recovery_frac=0.5, recovery_ticks=4*DAY,   wave_amp_pct=4,   wave_period_ticks=WAVE, tail_ticks=8*DAY,  dead_cat=True),
    "deadcat_65_trap":        dict(magnitude_pct=65, drop_ticks=1*DAY,    recovery_frac=0.6, recovery_ticks=4*DAY,   wave_amp_pct=3,   wave_period_ticks=WAVE, tail_ticks=10*DAY, dead_cat=True),
    "grind_80_slow_wavy":     dict(magnitude_pct=80, drop_ticks=12*DAY,   recovery_frac=0.15,recovery_ticks=3*DAY,   wave_amp_pct=5,   wave_period_ticks=WAVE, tail_ticks=5*DAY),
    "bear_grind_40_wavy":     dict(magnitude_pct=40, drop_ticks=10*DAY,   recovery_frac=0.3, recovery_ticks=3*DAY,   wave_amp_pct=4,   wave_period_ticks=WAVE, tail_ticks=5*DAY),
    "crash_60_v_recover":     dict(magnitude_pct=60, drop_ticks=2*DAY,    recovery_frac=1.0, recovery_ticks=4*DAY,   wave_amp_pct=5,   wave_period_ticks=WAVE, tail_ticks=6*DAY),
}


def cohort_setup():
    d = json.loads(COHORT.read_text())
    pairs = d["pairs"]
    if "BTC/USDT" not in pairs:
        pairs = ["BTC/USDT"] + pairs
    # betas from amplitude relative to BTC (higher-amp alts fall harder),
    # clamped to a sane band; BTC is the market (beta 1.0).
    amp = {r["pair"]: r.get("amplitude", 3.0) for r in d.get("detail", [])}
    btc_amp = amp.get("BTC/USDT", 3.0) or 3.0
    betas = {}
    for p in pairs:
        b = (amp.get(p, btc_amp) / btc_amp) if p != "BTC/USDT" else 1.0
        betas[p] = max(0.8, min(1.8, b))
    return pairs, betas


def series_to_1m(prices, start_price, anchor):
    """Turn a 1-per-minute price list into a 1m OHLCV DataFrame."""
    dates = pd.date_range(anchor, periods=len(prices), freq="1min", tz="UTC")
    close = pd.Series(prices, dtype="float64")
    openp = close.shift(1).fillna(start_price)
    hi = pd.concat([openp, close], axis=1).max(axis=1) * (1 + WICK)
    lo = pd.concat([openp, close], axis=1).min(axis=1) * (1 - WICK)
    return pd.DataFrame({
        "date": dates,
        "open": openp.values,
        "high": hi.values,
        "low": lo.values,
        "close": close.values,
        "volume": 1_000_000.0,   # nominal; backtest pairlist is static
    })


def resample_5m(df1m):
    g = df1m.set_index("date").resample("5min")
    df5 = pd.DataFrame({
        "open": g["open"].first(),
        "high": g["high"].max(),
        "low": g["low"].min(),
        "close": g["close"].last(),
        "volume": g["volume"].sum(),
    }).dropna().reset_index()
    return df5


def write_feather(df, pair, tf, scen_dir):
    fname = pair.replace("/", "_") + f"-{tf}.feather"
    df["date"] = df["date"].astype("datetime64[ms, UTC]")
    df.to_feather(scen_dir / fname)


def main():
    sl = json.loads(SHORTLIST.read_text())["shortlist_scenarios"]
    pairs, betas = cohort_setup()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    manifest = {}
    for scen in sl:
        params = TIER_B.get(scen)
        if not params:
            print(f"  (no minute-scale mapping for {scen}, skipping)")
            continue
        # Freqtrade resolves data under <datadir>/<exchange>/ - so the feathers
        # live in a "binance" subdir and run_synthetic points --datadir here.
        scen_dir = OUT_DIR / scen / "binance"
        scen_dir.mkdir(parents=True, exist_ok=True)
        panel = make_correlated_panel(pairs, betas=betas, seed=11, **params)
        n_min = len(next(iter(panel.values())))
        for pair, prices in panel.items():
            df1m = series_to_1m(prices, prices[0], START)
            write_feather(df1m, pair, "1m", scen_dir)
            write_feather(resample_5m(df1m), pair, "5m", scen_dir)
        end = START + pd.Timedelta(minutes=n_min - 1)
        manifest[scen] = {
            "timerange": f"{START:%Y%m%d}-{end:%Y%m%d}",
            "minutes": n_min, "pairs": pairs,
        }
        print(f"  {scen}: {n_min} min ({n_min/DAY:.1f}d), {len(pairs)} pairs "
              f"-> {manifest[scen]['timerange']}")

    (OUT_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"wrote {len(manifest)} scenarios to {OUT_DIR}")


if __name__ == "__main__":
    main()
