# WaveRiderDCA.py
#
# Freqtrade port of the "wave rider DCA [ajay_42]" Pine Script strategy.
# Ported from the standalone reference implementation in
# `freqtrade strategies/ftwr3.py`, which is the authoritative version of the
# "primed group" partial take-profit logic (comments there mark ftwr1/ftwr2 as
# earlier, less accurate attempts, and ftwr3 as "logic reconfirmed").
#
# Design note: Freqtrade's Trade object only tracks a single blended average
# entry price and remaining position amount - it has no concept of "this
# specific safety-order fill is still open, that one got closed" once a
# partial exit happens. To reproduce the original strategy's "primed group"
# behaviour (closing only a subset of fills - First+Last, or
# First+Last+SecondLast - whichever average is closer to price, while leaving
# the rest of the position open), this strategy keeps its own per-pair ledger
# of open lots in `self.custom_info` and drives real fills/exits through
# `adjust_trade_position` (positive stake = new safety order, negative stake =
# partial exit of the chosen group).

from datetime import datetime
from typing import Optional

from freqtrade.persistence import Trade
from freqtrade.strategy import IStrategy
from pandas import DataFrame


class WaveRiderDCA(IStrategy):
    """
    Wave Rider DCA - base order + safety-order ladder + "primed group"
    partial take-profit selection.
    """

    INTERFACE_VERSION = 3

    # ====================== DCA PARAMETERS ======================
    # (mirrors ftwr3.py's WaveRiderDCA dataclass fields)
    base_order_usd: float = 200.0
    safety_order_usd: float = 200.0
    max_safety_orders: int = 12
    safety_price_dev_pct: float = 2.0
    safety_volume_scale: float = 1.1
    safety_price_step_scale: float = 1.25
    take_profit_pct: float = 2.0
    take_profit_type: str = "% From total volume"  # or "% From base order"
    enable_stop_loss: bool = False
    stop_loss_pct: float = 18.0
    is_long: bool = True

    # ====================== RISK CONTROLS ======================
    # Hard ceiling on total USDT committed to one pair's open lots (base
    # order + open safety orders). Checked before every safety order - if
    # the next rung doesn't fit, it waits (no resize, no skip); a later
    # primed-group exit that frees capital lets it fire. NOT a stop-loss:
    # nothing ever force-closes at a loss.
    max_exposure_per_coin_usd: float = 1000.0
    # Lifetime number of full deals (fully-closed trades) allowed per pair.
    # Once reached, no new base order opens for that pair.
    max_deal_restarts: int = 3

    # ====================== FREQTRADE SETTINGS ======================
    timeframe = "5m"

    # ROI/stoploss are disabled here; exits are fully managed by
    # adjust_trade_position (primed-group TP) and custom_stoploss below.
    minimal_roi = {"0": 100}
    stoploss = -0.99
    trailing_stop = False
    use_custom_stoploss = True

    # REQUIRED for adjust_trade_position (safety orders + partial exits) to
    # ever be called. The old ftwr4.py port was missing this - safety orders
    # would silently never fire in live/dry-run without it.
    position_adjustment_enable = True
    max_entry_position_adjustment = max_safety_orders

    process_only_new_candles = True
    can_short = False  # strategy is long-only per is_long default; see note below

    startup_candle_count: int = 0

    # per-pair runtime ledger: { pair: {open_trades: [...], base_order_price,
    # count_executed_so, dev_cache} }
    custom_info: dict = {}

    # ==================== DCA MATH (ported 1:1 from ftwr3.py) ====================

    def _dev_cache_for(self, state: dict) -> tuple:
        return state["dev_cache"]

    def _calculate_stepped_deviation(self, so_index: int) -> float:
        if so_index <= 0:
            return 0.0
        dev = 0.0
        for i in range(1, so_index + 1):
            dev += self.safety_price_dev_pct * (self.safety_price_step_scale ** (i - 1))
        return dev

    def _stepped_deviation(self, state: dict, so_index: int) -> float:
        cache = state["dev_cache"]
        if 0 <= so_index < len(cache):
            return cache[so_index]
        return self._calculate_stepped_deviation(so_index)

    def _next_so_price(self, state: dict, so_index: int, bo_price: float) -> float:
        dev = self._stepped_deviation(state, so_index)
        return bo_price * (1 - dev / 100.0) if self.is_long else bo_price * (1 + dev / 100.0)

    def _next_so_size_usd(self, so_index: int) -> float:
        return self.safety_order_usd * (self.safety_volume_scale ** (so_index - 1))

    def _get_required_capital(self) -> float:
        total = self.base_order_usd
        for i in range(1, self.max_safety_orders + 1):
            total += self._next_so_size_usd(i)
        return total

    def _calculate_average(self, lots: list) -> float:
        total_value = sum(lot["price"] * lot["qty"] for lot in lots)
        total_qty = sum(lot["qty"] for lot in lots)
        return total_value / total_qty if total_qty else float("nan")

    def _evaluate_primed_group(self, state: dict, current_price: float):
        """
        Exact port of ftwr3.py's evaluate_primed_group():
        - Always includes the first (base) order.
        - Compares combo A (First+Last) vs combo B (First+Last+SecondLast),
          picks whichever average is closer to current price.
        """
        open_trades = state["open_trades"]
        if not open_trades:
            return [], float("nan")

        first_trade = open_trades[0]
        n = len(open_trades)

        combo_a = [first_trade, open_trades[-1]]
        avg_a = self._calculate_average(combo_a)

        if n >= 3:
            combo_b = [first_trade, open_trades[-2], open_trades[-1]]
            avg_b = self._calculate_average(combo_b)
        else:
            combo_b, avg_b = combo_a, avg_a

        dist_a = abs(avg_a - current_price)
        dist_b = abs(avg_b - current_price)

        if dist_b < dist_a and n >= 3:
            chosen_trades, chosen_avg = combo_b, avg_b
        else:
            chosen_trades, chosen_avg = combo_a, avg_a

        if self.take_profit_type == "% From total volume":
            tp_price = (
                chosen_avg * (1 + self.take_profit_pct / 100.0)
                if self.is_long
                else chosen_avg * (1 - self.take_profit_pct / 100.0)
            )
        else:  # "% From base order"
            chosen_qty = sum(lot["qty"] for lot in chosen_trades)
            req_usd = self.base_order_usd * self.take_profit_pct / 100.0
            tp_price = (
                (chosen_avg * chosen_qty + req_usd) / chosen_qty
                if self.is_long
                else (chosen_avg * chosen_qty - req_usd) / chosen_qty
            )

        return chosen_trades, tp_price

    # ==================== PER-PAIR STATE ====================

    def _new_state(self, base_order_price: float) -> dict:
        dev_cache = tuple(
            self._calculate_stepped_deviation(i) for i in range(self.max_safety_orders + 1)
        )
        return {
            "open_trades": [
                {"price": base_order_price, "qty": self.base_order_usd / base_order_price, "so_index": 0}
            ],
            "base_order_price": base_order_price,
            "count_executed_so": 0,
            "dev_cache": dev_cache,
        }

    def _get_state(self, trade: "Trade") -> dict:
        state = self.custom_info.get(trade.pair)
        if state is None:
            # Reconstruct from the trade itself if we don't have live state
            # (e.g. after a bot restart) - treat the trade's entry so far as
            # the base order only; safety-order history before the restart
            # can't be recovered exactly, so this is a best-effort fallback.
            state = self._new_state(trade.open_rate)
            self.custom_info[trade.pair] = state
        return state

    # ==================== FREQTRADE HOOKS ====================

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["enter_long"] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # No indicator-based exits - all exits are managed via
        # adjust_trade_position (primed-group TP) and custom_stoploss.
        return dataframe

    def custom_stake_amount(
        self,
        pair: str,
        current_time: datetime,
        current_rate: float,
        proposed_stake: float,
        min_stake: Optional[float],
        max_stake: float,
        leverage: float,
        entry_tag: Optional[str],
        side: str,
        **kwargs,
    ) -> float:
        # Base order size is controlled by base_order_usd, not the
        # config-level stake_amount.
        stake = self.base_order_usd
        if min_stake:
            stake = max(stake, min_stake)
        return min(stake, max_stake)

    def confirm_trade_entry(
        self,
        pair: str,
        order_type: str,
        amount: float,
        rate: float,
        time_in_force: str,
        current_time: datetime,
        entry_tag: Optional[str],
        side: str,
        **kwargs,
    ) -> bool:
        # Restart limit: only applies to brand-new deals, never to safety
        # orders on an already-open trade (robust regardless of whether
        # Freqtrade routes position adjustments through this callback).
        has_open_trade = bool(Trade.get_trades_proxy(pair=pair, is_open=True))
        if not has_open_trade:
            closed_deals = len(Trade.get_trades_proxy(pair=pair, is_open=False))
            if closed_deals >= self.max_deal_restarts:
                return False

        # A brand new deal is starting for this pair - (re)initialise the
        # per-pair ledger so a previous deal's closed-out state can't leak in.
        if pair not in self.custom_info or self.custom_info[pair].get("count_executed_so", 0) == 0:
            self.custom_info[pair] = self._new_state(rate)
        return True

    def adjust_trade_position(
        self,
        trade: "Trade",
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        min_stake: Optional[float],
        max_stake: float,
        current_entry_rate: float,
        current_exit_rate: float,
        current_entry_profit: float,
        current_exit_profit: float,
        **kwargs,
    ) -> Optional[float]:
        state = self._get_state(trade)

        # 1) Primed-group take-profit check (partial exit) takes priority.
        chosen, tp_price = self._evaluate_primed_group(state, current_rate)
        if chosen:
            tp_hit = current_rate >= tp_price if self.is_long else current_rate <= tp_price
            if tp_hit:
                group_qty = sum(lot["qty"] for lot in chosen)
                remaining_qty = sum(lot["qty"] for lot in state["open_trades"])
                is_final_group = group_qty >= remaining_qty - 1e-12

                state["open_trades"] = [lot for lot in state["open_trades"] if lot not in chosen]

                if is_final_group or not state["open_trades"]:
                    # Closing everything - let Freqtrade close the trade
                    # outright rather than leaving a dust remainder.
                    return -trade.stake_amount

                stake_to_exit = group_qty * current_rate
                return -min(stake_to_exit, trade.stake_amount * 0.999)

        # 2) Otherwise, check whether the next safety order should fill.
        executed = state["count_executed_so"]
        if executed >= self.max_safety_orders:
            return None

        so_index = executed + 1
        next_price = self._next_so_price(state, so_index, state["base_order_price"])
        hit = current_rate <= next_price if self.is_long else current_rate >= next_price
        if not hit:
            return None

        so_stake = self._next_so_size_usd(so_index)
        if min_stake:
            so_stake = max(so_stake, min_stake)
        so_stake = min(so_stake, max_stake)

        # Exposure cap: committed capital = every still-open lot at its
        # entry price. If this rung would push past the ceiling, wait -
        # don't resize it, don't skip to the next rung. A primed-group
        # exit that frees capital can let the same rung fire later.
        exposure_usd = sum(lot["price"] * lot["qty"] for lot in state["open_trades"])
        if exposure_usd + so_stake > self.max_exposure_per_coin_usd:
            return None

        state["open_trades"].append(
            {"price": current_rate, "qty": so_stake / current_rate, "so_index": so_index}
        )
        state["count_executed_so"] += 1
        return so_stake

    def custom_stoploss(
        self,
        pair: str,
        trade: "Trade",
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        **kwargs,
    ) -> float:
        if not self.enable_stop_loss:
            return 1.0  # never trigger the framework stoploss

        state = self.custom_info.get(pair)
        if not state:
            return 1.0

        max_dev = self._stepped_deviation(state, self.max_safety_orders)
        if self.stop_loss_pct <= max_dev:
            return 1.0  # SL would trigger before the DCA ladder is exhausted - disable it

        # Express stop_loss_pct (from base order price) as a fraction of
        # current_rate, which is what Freqtrade's custom_stoploss expects.
        base_price = state["base_order_price"]
        sl_price = (
            base_price * (1 - self.stop_loss_pct / 100.0)
            if self.is_long
            else base_price * (1 + self.stop_loss_pct / 100.0)
        )
        sl_fraction = (sl_price - current_rate) / current_rate
        return sl_fraction if self.is_long else -sl_fraction
