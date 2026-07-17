"""
Portfolio: runs up to max_coins independent Deals side by side.

Each coin's Deal is fully independent - its own base order, its own
ladder, its own 1000 USDT cap, its own restart count. Nothing is shared
between coins except that the portfolio won't let you add more coins
than config.max_coins, which is what actually bounds total capital at
risk: max_coins * max_exposure_per_coin_usd.
"""

from config import StrategyConfig
from deal import Deal


class Portfolio:
    def __init__(self, config: StrategyConfig, coins: list[str]):
        if len(coins) > config.max_coins:
            raise ValueError(
                f"Requested {len(coins)} coins but max_coins is {config.max_coins}"
            )
        self.config = config
        self.deals: dict[str, Deal] = {coin: Deal(coin, config) for coin in coins}

    def step(self, prices: dict[str, float]) -> list[dict]:
        """
        Advance every coin's deal by one price tick. `prices` maps
        coin -> current price; coins missing from `prices` are skipped
        for this tick (e.g. no data yet).
        """
        events = []
        for coin, deal in self.deals.items():
            if coin not in prices:
                continue
            events.extend(deal.step(prices[coin]))
        return events

    def total_exposure_usd(self) -> float:
        return sum(deal.exposure_usd for deal in self.deals.values())

    def max_possible_exposure_usd(self) -> float:
        return self.config.max_coins * self.config.max_exposure_per_coin_usd

    def snapshot(self) -> list[dict]:
        """One row per coin, useful for printing status during a run."""
        rows = []
        for coin, deal in self.deals.items():
            rows.append({
                "coin": coin,
                "state": deal.state,
                "open_orders": len(deal.open_fills),
                "exposure_usd": round(deal.exposure_usd, 2),
                "restart_count": deal.restart_count,
            })
        return rows
