"""
Tier-A synthetic stress sandbox (fast, no Docker, no market data).

Drives the pure-Python reference Portfolio/Deal over every scenario in
synthetic_paths.SCENARIO_CATALOGUE and measures, per scenario, the things
the STRATEGY PURPOSE actually cares about:

  - peak exposure (worst-case capital committed)  -> "capital safety"
  - trapped capital at the end (still-open deal)   -> "never trap capital"
  - unrealized loss on that trapped capital        -> how bad the trap is
  - realized skim PnL                              -> "escape profitably"

It then writes a danger-ranked shortlist to synthetic_shortlist.json. The
nastiest, most DISTINCT scenarios are the ones worth spending a real
(10-17 min) Freqtrade backtest on in Tier B - this sandbox exists to make
that curation evidence-based instead of arbitrary.

IMPORTANT: the reference sim has NO governors (no coin-brake, crash-freeze,
aggregate ceiling, or lifecycle) - it is the RAW ladder+cap+skim core. So a
trap found here is a property of the base mechanic; Tier B then measures how
much the governors reduce it. Do not read these numbers as the live system's
outcome.

Run:  python run_synthetic_sandbox.py
"""

import json
import sys
from pathlib import Path

from config import StrategyConfig
from portfolio import Portfolio
from synthetic_paths import SCENARIO_CATALOGUE, make_shock_path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = Path(__file__).resolve().parent


def base_config() -> StrategyConfig:
    # Mirrors the live ladder geometry (config.json wave_rider section):
    # small BO, 2% spacing, 1.1 volume scale, 1000 cap, single coin per run.
    return StrategyConfig(
        strategy_type="long",
        take_profit_perc=2.0,
        base_order_size_usd=10.0,
        safety_order_size_usd=10.0,
        max_safety_orders=25,
        safety_order_price_deviation_perc=2.0,
        safety_order_volume_scale=1.1,
        safety_order_price_step_scale=1.0,
        max_exposure_per_coin_usd=1000.0,
        max_deal_restarts=100,   # effectively unlimited (quality-floor era)
        max_coins=1,
    )


def run_scenario(name: str, params: dict) -> dict:
    config = base_config()
    coin = "SYN"
    portfolio = Portfolio(config, [coin])
    prices = make_shock_path(**params)

    peak_exposure = 0.0
    realized_pnl = 0.0
    for price in prices:
        events = portfolio.step({coin: price})
        for e in events:
            if e["type"] == "SKIM_CLOSE":
                realized_pnl += e["realized_pnl_usd"]
        peak_exposure = max(peak_exposure, portfolio.total_exposure_usd())

    deal = portfolio.deals[coin]
    final_price = prices[-1]

    # Trapped capital = a still-ACTIVE deal at the end of the scenario, plus
    # how far underwater its open fills are marked at the final price.
    trapped_usd = deal.exposure_usd if deal.state == "ACTIVE" else 0.0
    unreal_loss_pct = 0.0
    if trapped_usd > 0 and deal.open_fills:
        cost = sum(f.price * f.qty for f in deal.open_fills)
        mark = sum(final_price * f.qty for f in deal.open_fills)
        unreal_loss_pct = round((mark - cost) / cost * 100.0, 2)

    cap = config.max_exposure_per_coin_usd
    return {
        "scenario": name,
        "params": params,
        "peak_exposure_usd": round(peak_exposure, 2),
        "peak_exposure_pct_of_cap": round(peak_exposure / cap * 100.0, 1),
        "realized_skim_pnl_usd": round(realized_pnl, 2),
        "trapped_capital_usd": round(trapped_usd, 2),
        "trapped_unreal_loss_pct": unreal_loss_pct,
        "deals_closed": deal.restart_count,
        "final_state": deal.state,
        "ticks": len(prices),
    }


def danger_score(r: dict) -> float:
    """
    Higher = more dangerous to CAPITAL. Trapped capital dominates (that is the
    cardinal sin per the purpose), weighted by how deep underwater it is;
    peak exposure is a secondary term.
    """
    trap = r["trapped_capital_usd"]
    depth = abs(min(0.0, r["trapped_unreal_loss_pct"])) / 100.0
    return trap * (1.0 + depth) + 0.25 * r["peak_exposure_usd"]


def main():
    results = [run_scenario(n, p) for n, p in SCENARIO_CATALOGUE.items()]
    for r in results:
        r["danger_score"] = round(danger_score(r), 2)
    results.sort(key=lambda r: r["danger_score"], reverse=True)

    # Console table.
    print(f"{'scenario':<26} {'peakExp$':>9} {'peak%cap':>8} "
          f"{'skimPnL$':>9} {'trapped$':>9} {'trapLoss%':>9} "
          f"{'closed':>6} {'danger':>8}")
    print("-" * 92)
    for r in results:
        print(f"{r['scenario']:<26} {r['peak_exposure_usd']:>9.0f} "
              f"{r['peak_exposure_pct_of_cap']:>7.0f}% {r['realized_skim_pnl_usd']:>9.2f} "
              f"{r['trapped_capital_usd']:>9.0f} {r['trapped_unreal_loss_pct']:>9.2f} "
              f"{r['deals_closed']:>6d} {r['danger_score']:>8.1f}")

    # Curate a SMALL, DISTINCT shortlist for Tier B - a real Freqtrade
    # backtest is ~10-17 min, and each shortlisted scenario runs twice
    # (governors on/off), so budget forces selectivity. Take the top-N by
    # danger, then always append the best-recovering scenario as a "strategy
    # should thrive here" control if it isn't already in.
    TOP_N = 5
    shortlist = results[:TOP_N]
    control = min(results, key=lambda r: r["danger_score"])
    if control["scenario"] not in [r["scenario"] for r in shortlist]:
        shortlist = shortlist + [control]

    out = {
        "generated_by": "run_synthetic_sandbox.py",
        "note": "Reference sim = RAW ladder+cap+skim, NO governors. Tier B "
                "measures how much the live governors reduce these traps.",
        "ranked_results": results,
        "shortlist_scenarios": [r["scenario"] for r in shortlist],
    }
    path = HERE / "synthetic_shortlist.json"
    path.write_text(json.dumps(out, indent=2))
    print(f"\nShortlist ({len(shortlist)}): {out['shortlist_scenarios']}")
    print(f"Wrote {path}")


if __name__ == "__main__":
    main()
