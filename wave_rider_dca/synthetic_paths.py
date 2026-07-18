"""
Synthetic shock-path generator (pure stdlib, deterministic).

Purpose: build price paths that are DELIBERATELY WORSE than anything in the
recorded history, so we can stress the Wave Rider capital math past the edge
of the real backtests. This is the single source of truth for the shock
maths - both the fast pure-Python sandbox (run_synthetic_sandbox.py) and the
real-Freqtrade data generator (../freqtrade/user_data/scripts/gen_synthetic_data.py)
import from here so the two tiers describe the SAME scenarios.

A path is built from four independent ideas, each a knob:

  1. DEPTH   - how far price ultimately falls from the start (magnitude_pct).
  2. SPEED   - how many ticks the fall takes (drop_ticks); 1 = a gap/flash.
  3. RECOVERY- how much of the fall is later retraced (recovery_frac:
               1.0 = full V, 0.5 = half bounce, 0.0 = flatline at the low,
               and a "dead cat" that bounces then makes a lower low).
  4. WAVES   - oscillation superimposed on the trend (wave_amp_pct /
               wave_period_ticks). Waves are the strategy's FUEL: a wavy
               crash lets it skim on the way down; a smooth one-way crash
               with no waves is the capital trap we most want to find.

Everything is deterministic given `seed`, so a shortlisted scenario can be
regenerated identically for the real backtest.
"""

import math
import random


def make_shock_path(
    magnitude_pct: float,
    drop_ticks: int,
    recovery_frac: float,
    recovery_ticks: int,
    wave_amp_pct: float,
    wave_period_ticks: int,
    tail_ticks: int,
    start_price: float = 100.0,
    dead_cat: bool = False,
    noise_frac: float = 0.004,
    seed: int = 7,
) -> list[float]:
    """
    Return a list of prices describing one shock scenario.

    Segments: a short calm lead-in, the fall to the trough, an optional
    recovery, then a tail that holds the final level. A sine wave of
    `wave_amp_pct` (relative to the local trend level) and a little noise
    are layered on top of the whole thing.
    """
    rng = random.Random(seed)
    trough = start_price * (1.0 - magnitude_pct / 100.0)

    # Recovery target: how far back up from the trough we retrace.
    recovered = trough + (start_price - trough) * max(0.0, recovery_frac)

    lead_ticks = max(4, wave_period_ticks)
    trend: list[float] = []

    # 1) calm lead-in at the start price
    trend.extend([start_price] * lead_ticks)

    # 2) the fall (linear from start to trough over drop_ticks)
    for step in range(1, max(1, drop_ticks) + 1):
        t = step / max(1, drop_ticks)
        trend.append(start_price + (trough - start_price) * t)

    # 3) optional recovery
    if recovery_ticks > 0 and recovery_frac > 0:
        if dead_cat:
            # bounce toward `recovered`, then roll over to a LOWER low than
            # the first trough - the classic bull-trap that strands capital
            # bought on the bounce.
            bounce_top = trough + (recovered - trough) * 0.6
            lower_low = trough * 0.92
            half = max(1, recovery_ticks // 2)
            for step in range(1, half + 1):
                t = step / half
                trend.append(trough + (bounce_top - trough) * t)
            for step in range(1, (recovery_ticks - half) + 1):
                t = step / max(1, recovery_ticks - half)
                trend.append(bounce_top + (lower_low - bounce_top) * t)
            final_level = lower_low
        else:
            for step in range(1, recovery_ticks + 1):
                t = step / recovery_ticks
                trend.append(trough + (recovered - trough) * t)
            final_level = recovered
    else:
        final_level = trough

    # 4) tail holding the final level
    trend.extend([final_level] * max(0, tail_ticks))

    # Layer waves + noise on top of the trend.
    prices: list[float] = []
    for i, level in enumerate(trend):
        if wave_period_ticks > 0 and wave_amp_pct > 0:
            wave = math.sin(2 * math.pi * i / wave_period_ticks)
            level = level * (1.0 + (wave_amp_pct / 100.0) * wave)
        level = level * (1.0 + rng.uniform(-noise_frac, noise_frac))
        prices.append(round(max(level, 1e-6), 6))
    return prices


def make_correlated_panel(
    coins: list[str],
    magnitude_pct: float,
    drop_ticks: int,
    recovery_frac: float,
    recovery_ticks: int,
    wave_amp_pct: float,
    wave_period_ticks: int,
    tail_ticks: int,
    betas: dict[str, float] | None = None,
    dead_cat: bool = False,
    seed: int = 7,
) -> dict[str, list[float]]:
    """
    A multi-coin panel driven by ONE shared shock factor (the "market"),
    scaled per coin by a beta, plus independent per-coin noise/phase. This
    models a correlated crash: every coin gaps down together (the case the
    per-coin brake alone can miss and the aggregate/crash governors exist
    for). beta > 1 = higher-amplitude alt that falls harder than the market.
    """
    betas = betas or {c: 1.0 for c in coins}
    # Shared market factor as a fractional deviation from the start level.
    market = make_shock_path(
        magnitude_pct, drop_ticks, recovery_frac, recovery_ticks,
        wave_amp_pct, wave_period_ticks, tail_ticks,
        start_price=100.0, dead_cat=dead_cat, noise_frac=0.0, seed=seed,
    )
    market_frac = [p / 100.0 - 1.0 for p in market]  # deviation from 1.0

    # A coin can crash hard but not to literally zero. Floor the beta-scaled
    # factor so the deepest a coin reaches is FLOOR_FRAC of its start (here
    # -92%). Without this, beta>1 x an 80-90% market crash drives prices to ~0,
    # which trips Freqtrade's mandatory -99% stop backstop and contaminates the
    # governor comparison with "stop_loss" exits the no-stop-loss strategy
    # would never actually take.
    FLOOR_FRAC = 0.08
    panel: dict[str, list[float]] = {}
    for idx, coin in enumerate(coins):
        beta = betas.get(coin, 1.0)
        rng = random.Random(seed + 101 * (idx + 1))
        series = []
        for i, mf in enumerate(market_frac):
            # phase-shifted idiosyncratic wobble so coins are correlated but
            # not identical.
            wobble = rng.uniform(-0.006, 0.006)
            factor = max(FLOOR_FRAC, 1.0 + beta * mf)
            level = 100.0 * factor * (1.0 + wobble)
            series.append(round(max(level, 1e-6), 6))
        panel[coin] = series
    return panel


# A named catalogue of stress scenarios, ordered roughly gentlest -> nastiest.
# Each is a kwargs dict for make_shock_path. The sandbox runs all of them; the
# nastiest survivors get promoted to real Freqtrade backtests.
SCENARIO_CATALOGUE: dict[str, dict] = {
    # historical-ish reference points (for calibration)
    "bear_grind_40_wavy":      dict(magnitude_pct=40, drop_ticks=180, recovery_frac=0.3,
                                    recovery_ticks=60, wave_amp_pct=4, wave_period_ticks=24, tail_ticks=60),
    "crash_60_v_recover":      dict(magnitude_pct=60, drop_ticks=40, recovery_frac=1.0,
                                    recovery_ticks=80, wave_amp_pct=5, wave_period_ticks=20, tail_ticks=40),
    # beyond-history: deep, fast, and/or un-recovering
    "flash_60_no_recover":     dict(magnitude_pct=60, drop_ticks=3, recovery_frac=0.0,
                                    recovery_ticks=0, wave_amp_pct=2, wave_period_ticks=18, tail_ticks=120),
    "flash_80_no_recover":     dict(magnitude_pct=80, drop_ticks=3, recovery_frac=0.0,
                                    recovery_ticks=0, wave_amp_pct=2, wave_period_ticks=18, tail_ticks=120),
    "smooth_70_no_waves":      dict(magnitude_pct=70, drop_ticks=90, recovery_frac=0.0,
                                    recovery_ticks=0, wave_amp_pct=0.3, wave_period_ticks=18, tail_ticks=120),
    "deadcat_65_trap":         dict(magnitude_pct=65, drop_ticks=30, recovery_frac=0.6,
                                    recovery_ticks=80, wave_amp_pct=3, wave_period_ticks=22, tail_ticks=120,
                                    dead_cat=True),
    "grind_80_slow_wavy":      dict(magnitude_pct=80, drop_ticks=300, recovery_frac=0.15,
                                    recovery_ticks=60, wave_amp_pct=5, wave_period_ticks=26, tail_ticks=80),
    "flash_50_then_flatline":  dict(magnitude_pct=50, drop_ticks=2, recovery_frac=0.0,
                                    recovery_ticks=0, wave_amp_pct=1, wave_period_ticks=18, tail_ticks=200),
    "double_dip_75":           dict(magnitude_pct=75, drop_ticks=50, recovery_frac=0.5,
                                    recovery_ticks=100, wave_amp_pct=4, wave_period_ticks=24, tail_ticks=120,
                                    dead_cat=True),
    "wavy_90_extreme":         dict(magnitude_pct=90, drop_ticks=120, recovery_frac=0.1,
                                    recovery_ticks=40, wave_amp_pct=6, wave_period_ticks=20, tail_ticks=80),
}
