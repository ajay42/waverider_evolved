"""
A small, self-contained demo that drives the strategy over a made-up
price path so you can see base orders, safety orders, the exposure cap,
skim-closes, and deal restarts all happen and print out what they did.

This is NOT a real backtest (no historical data, no fees, no slippage) -
it's a sanity check that the state machine in deal.py behaves the way we
designed it to, before porting the same logic into Freqtrade.

Run it with:
    python simulate.py
"""

import random

from config import StrategyConfig
from portfolio import Portfolio


def make_price_series(waypoints: list[float], steps_between: int = 10,
                       noise_frac: float = 0.03, seed: int = 7) -> list[float]:
    """
    Build a price series by walking between hand-picked waypoints (straight
    line) with a little random noise mixed in, so it feels like a real
    (if simplified) chart instead of a perfectly smooth line.
    """
    random.seed(seed)
    prices = []
    for i in range(len(waypoints) - 1):
        start, end = waypoints[i], waypoints[i + 1]
        for step in range(steps_between):
            t = step / steps_between
            base = start + (end - start) * t
            wobble = random.uniform(-noise_frac, noise_frac) * base
            prices.append(round(base + wobble, 4))
    prices.append(waypoints[-1])
    return prices


def format_event(e: dict) -> str:
    coin = e["coin"]
    if e["type"] == "BASE_ORDER_OPENED":
        return (f"{coin:>8s} | BASE ORDER opened   id={e['fill_id']:<14s} "
                f"price={e['price']:8.2f}  size=${e['size_usd']:7.2f}  "
                f"(deal #{e['restart_count'] + 1})")
    if e["type"] == "SAFETY_ORDER_FILLED":
        return (f"{coin:>8s} | SAFETY ORDER #{e['ladder_index']:<2d} filled  "
                f"id={e['fill_id']:<14s} price={e['price']:8.2f}  "
                f"size=${e['size_usd']:7.2f}  exposure=${e['exposure_usd']:7.2f}")
    if e["type"] == "SKIM_CLOSE":
        closed = ",".join(e["closed_fill_ids"])
        tail = "  -> DEAL FULLY CLOSED" if e["deal_fully_closed"] else ""
        return (f"{coin:>8s} | SKIM CLOSE          closed=[{closed}] "
                f"price={e['close_price']:8.2f}  pnl=${e['realized_pnl_usd']:+7.2f}{tail}")
    return str(e)


def main():
    config = StrategyConfig(
        strategy_type="long",
        take_profit_perc=2.0,
        base_order_size_usd=20.0,
        safety_order_size_usd=20.0,
        max_safety_orders=15,
        safety_order_price_deviation_perc=2.0,
        safety_order_volume_scale=1.1,
        safety_order_price_step_scale=1.05,
        max_exposure_per_coin_usd=1000.0,
        max_deal_restarts=3,
        max_coins=10,
    )

    coin = "BTCUSDT"
    portfolio = Portfolio(config, [coin])

    # A hand-picked path: dip -> partial recovery -> deeper dip (deep enough
    # to hit the exposure cap) -> big recovery -> repeat, so the demo shows
    # every mechanic: safety orders filling, skim-closes, the cap freezing
    # new orders, and a deal fully closing so a new one can restart.
    waypoints = [100, 100, 90, 80, 70, 60, 50, 65, 85, 100,
                 95, 80, 65, 50, 40, 55, 80, 105, 100]
    prices = make_price_series(waypoints, steps_between=12)

    for tick, price in enumerate(prices):
        events = portfolio.step({coin: price})
        for event in events:
            print(f"[tick {tick:4d}] price={price:8.2f}  {format_event(event)}")

    print("\n--- Final snapshot ---")
    for row in portfolio.snapshot():
        print(row)

    print(f"\nTotal exposure now: ${portfolio.total_exposure_usd():.2f} "
          f"(portfolio ceiling: ${portfolio.max_possible_exposure_usd():.2f})")


if __name__ == "__main__":
    main()
