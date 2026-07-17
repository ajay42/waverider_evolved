"""
Deal: the state machine for one coin's DCA cycle.

A "deal" is the whole lifecycle for one coin: open a base order, add safety
orders as price moves against it (up to a hard USD cap), and skim-close the
outermost pair of open orders for profit whenever price recovers far enough.
When every open order has been skimmed off, the deal is fully closed and a
new one may start (up to a limited number of restarts).

Read this file top to bottom - each method is one step of that cycle, in
the order they happen.
"""

from dataclasses import dataclass
from typing import Optional

from config import StrategyConfig
from ladder import LadderRung, build_ladder

FLAT = "FLAT"
ACTIVE = "ACTIVE"


@dataclass
class Fill:
    """One order that has actually been filled and is still open."""
    id: str
    kind: str          # "BO" or "SO"
    ladder_index: int  # 0 for the base order, 1..N for safety orders
    price: float
    qty: float
    size_usd: float


class Deal:
    def __init__(self, coin: str, config: StrategyConfig):
        self.coin = coin
        self.config = config
        self.is_long = config.is_long

        self.state = FLAT
        self.restart_count = 0

        self.base_price: Optional[float] = None
        self.ladder: list[LadderRung] = []
        self.next_so_index = 1  # which ladder rung we're waiting on next

        self.open_fills: list[Fill] = []
        self.exposure_usd = 0.0

        self._fill_seq = 0

    # ---- capital accounting ----

    def remaining_capacity(self) -> float:
        """
        How much more USD this coin's deal is allowed to commit right now.
        Checked before *every* new safety order - fresh ones from the
        ladder or, if a future version adds order-recycling, reopened
        ones too. If a rung's size doesn't fit, it simply doesn't fire
        yet; nothing forces a loss to make room.
        """
        return self.config.max_exposure_per_coin_usd - self.exposure_usd

    def _next_fill_id(self, kind: str) -> str:
        self._fill_seq += 1
        return f"{self.coin}-{kind}-{self._fill_seq}"

    # ---- opening a deal ----

    def can_start_new_deal(self) -> bool:
        return self.state == FLAT and self.restart_count < self.config.max_deal_restarts

    def start_base_order(self, price: float) -> Optional[Fill]:
        if not self.can_start_new_deal():
            return None

        qty = self.config.base_order_size_usd / price
        fill = Fill(
            id=self._next_fill_id("BO"),
            kind="BO",
            ladder_index=0,
            price=price,
            qty=qty,
            size_usd=self.config.base_order_size_usd,
        )

        self.state = ACTIVE
        self.base_price = price
        self.ladder = build_ladder(self.config, price)
        self.next_so_index = 1
        self.open_fills = [fill]
        self.exposure_usd = fill.size_usd

        return fill

    # ---- adding safety orders ----

    def try_fill_next_safety_order(self, current_price: float) -> Optional[Fill]:
        """
        Check the *one* next rung in the ladder against the current price.
        Only ever considers one rung at a time, in order - never skips
        ahead and never picks an arbitrary price, matching the
        "pre-calculated points only" rule.
        """
        if self.state != ACTIVE:
            return None
        if self.next_so_index > len(self.ladder):
            return None  # ladder exhausted

        rung = self.ladder[self.next_so_index - 1]

        if self.is_long:
            triggered = current_price <= rung.trigger_price
        else:
            triggered = current_price >= rung.trigger_price

        if not triggered:
            return None

        if rung.size_usd > self.remaining_capacity():
            # Price reached the rung, but the 1000 USDT cap has no room.
            # We do NOT skip ahead or resize - we just wait. If a later
            # skim-close frees up capacity and price is still at/through
            # this rung, it will fire then.
            return None

        fill = Fill(
            id=self._next_fill_id("SO"),
            kind="SO",
            ladder_index=rung.index,
            price=rung.trigger_price,
            qty=rung.qty,
            size_usd=rung.size_usd,
        )
        self.open_fills.append(fill)
        self.exposure_usd += fill.size_usd
        self.next_so_index += 1

        return fill

    # ---- skim-closing for profit ----

    def find_skim_close(self, current_price: float) -> Optional[tuple[list[Fill], float]]:
        """
        Look at the outermost open orders (oldest still-open and
        newest still-open) and check whether price has recovered far
        enough past their blended average to take profit on just those
        two. If only one order is left open, it's judged on its own.

        Returns (fills_to_close, blended_avg_price) if triggered, else None.
        """
        if self.state != ACTIVE or not self.open_fills:
            return None

        if len(self.open_fills) == 1:
            pair = [self.open_fills[0]]
        else:
            pair = [self.open_fills[0], self.open_fills[-1]]

        total_cost = sum(f.price * f.qty for f in pair)
        total_qty = sum(f.qty for f in pair)
        avg_price = total_cost / total_qty

        if self.is_long:
            tp_price = avg_price * (1 + self.config.take_profit_perc / 100)
            triggered = current_price >= tp_price
        else:
            tp_price = avg_price * (1 - self.config.take_profit_perc / 100)
            triggered = current_price <= tp_price

        if not triggered:
            return None
        return pair, tp_price

    def apply_skim_close(self, fills_to_close: list[Fill], close_price: float) -> dict:
        """
        Actually close the given fills at close_price. Freed capital just
        reduces exposure_usd - it is NOT automatically redeployed into a
        new order ("non-renewal"). If that empties the deal entirely, the
        deal is considered fully wound down and a new one may start later.
        """
        realized_pnl = 0.0
        for f in fills_to_close:
            if self.is_long:
                realized_pnl += (close_price - f.price) * f.qty
            else:
                realized_pnl += (f.price - close_price) * f.qty
            self.exposure_usd -= f.size_usd
            self.open_fills.remove(f)

        deal_fully_closed = len(self.open_fills) == 0
        if deal_fully_closed:
            self.state = FLAT
            self.restart_count += 1
            self.base_price = None
            self.ladder = []
            self.next_so_index = 1
            self.exposure_usd = 0.0

        return {
            "coin": self.coin,
            "closed_fill_ids": [f.id for f in fills_to_close],
            "close_price": close_price,
            "realized_pnl_usd": realized_pnl,
            "deal_fully_closed": deal_fully_closed,
            "restart_count": self.restart_count,
        }

    # ---- one tick of simulated/live time ----

    def step(self, current_price: float) -> list[dict]:
        """
        Advance this deal by one price tick. Order of operations matters:
        try to take profit first (free up capacity), then try to add a
        safety order (which may now fit under the freed-up cap), then -
        only if we're flat - try to start a fresh deal.
        """
        events = []

        skim = self.find_skim_close(current_price)
        if skim is not None:
            fills_to_close, tp_price = skim
            result = self.apply_skim_close(fills_to_close, current_price)
            events.append({"type": "SKIM_CLOSE", **result})

        so_fill = self.try_fill_next_safety_order(current_price)
        if so_fill is not None:
            events.append({
                "type": "SAFETY_ORDER_FILLED",
                "coin": self.coin,
                "fill_id": so_fill.id,
                "ladder_index": so_fill.ladder_index,
                "price": so_fill.price,
                "size_usd": so_fill.size_usd,
                "exposure_usd": self.exposure_usd,
            })

        if self.state == FLAT and self.can_start_new_deal():
            bo_fill = self.start_base_order(current_price)
            if bo_fill is not None:
                events.append({
                    "type": "BASE_ORDER_OPENED",
                    "coin": self.coin,
                    "fill_id": bo_fill.id,
                    "price": bo_fill.price,
                    "size_usd": bo_fill.size_usd,
                    "restart_count": self.restart_count,
                })

        return events
