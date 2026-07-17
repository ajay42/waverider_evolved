"""
Strategy configuration for Wave Rider DCA.

This is a plain-language settings sheet. Every field here corresponds to a
"knob" from the original Pine Script strategy, plus the risk-control knobs
we added on top of it (exposure cap, restart limit).

Nothing in this file *does* anything by itself - it just describes the
strategy. The actual logic that reads these numbers lives in ladder.py and
deal.py.
"""

from dataclasses import dataclass


@dataclass
class StrategyConfig:
    # --- direction ---
    # "long" buys dips and sells into strength. "short" is the mirror image.
    strategy_type: str = "long"

    # --- take profit ---
    # How far above (long) or below (short) the blended entry price of the
    # two outermost open orders must move before we skim-close them.
    take_profit_perc: float = 2.0

    # --- base order (BO) ---
    # Size in USDT of the very first order that opens a deal.
    base_order_size_usd: float = 10.0

    # --- safety order (SO) ladder ---
    # Size in USDT of the *first* safety order. Later safety orders scale up
    # from this using safety_order_volume_scale.
    safety_order_size_usd: float = 10.0

    # Upper bound on how many safety orders the ladder is allowed to have.
    # In practice max_exposure_per_coin_usd usually runs out before this
    # does - this is just a hard ceiling so the ladder can't grow forever.
    max_safety_orders: int = 15

    # % price move away from the base order price that triggers safety
    # order #1. Each subsequent safety order needs a bigger move than the
    # last one if safety_order_price_step_scale > 1 (see ladder.py).
    safety_order_price_deviation_perc: float = 2.0

    # Multiplier applied to each successive safety order's USD size.
    # 1.1 means safety order #2 is 10% bigger than #1, #3 is 10% bigger
    # than #2, and so on - this is the "martingale" part of the strategy.
    safety_order_volume_scale: float = 1.1

    # Multiplier applied to the *gap* between successive safety order
    # trigger prices. 1.0 means every safety order is the same % apart.
    # >1.0 means the ladder spreads out further apart the deeper it goes.
    safety_order_price_step_scale: float = 1.0

    # --- risk controls (not part of the original Pine script) ---
    # Hard ceiling on total USDT committed to a single coin's open orders
    # at any one time (base order + all currently-open safety orders).
    # This replaces "keep adding safety orders forever" with a fixed
    # worst-case capital commitment per coin.
    max_exposure_per_coin_usd: float = 1000.0

    # How many times a full deal (base order -> safety orders -> fully
    # closed) is allowed to restart for a single coin. Once a coin has
    # completed this many deals, no new base order is opened for it -
    # the strategy stops trading that coin until reset by hand.
    max_deal_restarts: int = 3

    # --- portfolio ---
    # How many coins the strategy is allowed to run at once. Each coin gets
    # its own independent Deal with its own max_exposure_per_coin_usd cap,
    # so worst-case total capital at risk is max_coins * max_exposure_per_coin_usd.
    max_coins: int = 10

    @property
    def is_long(self) -> bool:
        return self.strategy_type == "long"
