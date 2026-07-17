"""
The safety order (SO) ladder: a fixed, pre-calculated list of "if price
reaches here, place an order this big" rungs.

Everything here is a pure function - given the same inputs you always get
the same outputs. That's deliberate: the ladder is calculated once, in
full, the moment a deal's base order fills. Nothing about it is decided
on the fly or randomly - each rung's price and size is known in advance.
"""

from dataclasses import dataclass

from config import StrategyConfig


def stepped_deviation_percent(so_index: int, deviation_perc: float, step_scale: float) -> float:
    """
    Cumulative % distance of safety order `so_index` from the base order
    price.

    Each step away from the base order adds deviation_perc, scaled up by
    step_scale for every step taken so far. With step_scale == 1.0 this is
    just deviation_perc * so_index (evenly spaced rungs). With
    step_scale > 1.0 later rungs are spaced further apart than earlier ones.

    so_index is 1-based (so_index=1 is the first safety order).
    """
    if so_index <= 0:
        return 0.0

    total = 0.0
    for step in range(1, so_index + 1):
        total += deviation_perc * (step_scale ** (step - 1))
    return total


def so_trigger_price(so_index: int, base_price: float, deviation_perc: float,
                      step_scale: float, is_long: bool) -> float:
    """Price at which safety order `so_index` should fire."""
    deviation = stepped_deviation_percent(so_index, deviation_perc, step_scale)
    if is_long:
        # Long deals average down: each safety order triggers lower than the last.
        return base_price * (1 - deviation / 100)
    else:
        # Short deals average up: each safety order triggers higher than the last.
        return base_price * (1 + deviation / 100)


def so_size_usd(so_index: int, safety_order_size_usd: float, volume_scale: float) -> float:
    """USD size of safety order `so_index`. Grows geometrically with volume_scale."""
    return safety_order_size_usd * (volume_scale ** (so_index - 1))


@dataclass
class LadderRung:
    """One precomputed safety order: where it triggers and how big it is."""
    index: int          # 1-based position in the ladder
    trigger_price: float
    size_usd: float
    qty: float           # size_usd / trigger_price


def build_ladder(config: StrategyConfig, base_price: float) -> list[LadderRung]:
    """
    Precompute the full safety order ladder for a deal, given the base
    order's fill price. Called once, right after the base order fills -
    the resulting list never changes for the life of that deal.
    """
    rungs = []
    for so_index in range(1, config.max_safety_orders + 1):
        trigger_price = so_trigger_price(
            so_index,
            base_price,
            config.safety_order_price_deviation_perc,
            config.safety_order_price_step_scale,
            config.is_long,
        )
        size_usd = so_size_usd(so_index, config.safety_order_size_usd, config.safety_order_volume_scale)
        qty = size_usd / trigger_price
        rungs.append(LadderRung(so_index, trigger_price, size_usd, qty))
    return rungs
