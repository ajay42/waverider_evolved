"""
WaveRiderDCA - Freqtrade port of the confirmed Wave Rider DCA specification.

Authoritative spec: `wave_rider_dca/REGENERATION_PROMPT.md` (and the pure-Python
reference implementation next to it). Entry and exit behaviour - partial and
full - follows that spec ONLY:

  * A base order (BO) opens immediately whenever the pair is flat - there is
    no entry signal; the strategy always wants to be in a deal.
  * Safety orders (SOs) fill one at a time at PRE-CALCULATED ladder prices
    (never ad-hoc), each gated by the hard per-coin exposure cap. A rung that
    doesn't fit the cap WAITS - it is never resized or skipped.
  * Profit is taken by SKIM-CLOSING: when price recovers past the take-profit
    level of the two OUTERMOST open fills (oldest + newest), close only those
    two (or the single last fill), leaving the middle of the ladder open.
    This first+last-only partial exit is the defining "wave rider" mechanic.
  * Non-renewal: capital freed by a skim only reduces exposure - nothing is
    automatically re-opened, and there is NO stop-loss anywhere.
  * When every fill has been skimmed off, the deal is fully closed. A pair is
    allowed `max_deal_restarts` full deals, lifetime; then it stops trading.

Freqtrade-specific adaptations (kept as thin as possible):
  * Freqtrade's Trade object only knows a single blended position, so the
    per-fill ledger the spec requires ("open_fills") is kept in persistent
    trade custom data (survives bot restarts, unlike an in-memory dict).
  * The ledger records ACTUAL fill prices/amounts from executed orders
    (order_filled callback) so its math always matches the real wallet.
  * Entries/exits are placed through adjust_trade_position: positive stake =
    next safety order, negative stake = skim-close of the outer pair.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from freqtrade.exchange import timeframe_to_minutes
from freqtrade.persistence import Trade
from freqtrade.strategy import IStrategy, informative
from pandas import DataFrame

logger = logging.getLogger(__name__)

# Phase ribbon series (see plot_config): each phase gets its own bar series
# so the subplot renders as one color-coded strip.
PHASE_NAMES = ("grace", "wr", "grid", "decision", "override")


class WaveRiderDCA(IStrategy):

    INTERFACE_VERSION = 3

    # ================= SPEC PARAMETERS (config.py of the reference) =================
    # These are the spec DEFAULTS. Every one of them can be overridden from
    # the "wave_rider" section of config.json (see bot_start below), so the
    # workflow for tuning is: edit config.json -> click "Reload Config" in
    # FreqUI. No code edit, no container restart.
    take_profit_perc: float = 2.0            # % past outer-pair avg that triggers a skim
    base_order_size_usd: float = 10.0        # USD size of the deal-opening order
    safety_order_size_usd: float = 10.0      # USD size of SO #1
    max_safety_orders: int = 15              # hard ceiling on ladder length
    safety_order_price_deviation_perc: float = 2.0  # % move from BO price for SO #1
    safety_order_volume_scale: float = 1.1   # geometric growth of SO sizes
    safety_order_price_step_scale: float = 1.0      # spacing growth of SO triggers
    max_exposure_per_coin_usd: float = 1000.0  # hard cap: BO + open SOs per pair
    max_deal_restarts: int = 3               # full deals allowed per pair per stint
    #   "per stint": counted since the pair joined the active list (see
    #   pairlist_state.json, written by scripts/pairlist_updater.py). When the
    #   dynamic pairlist later re-adds a retired coin, it gets a fresh
    #   allowance. Without a state file this falls back to a lifetime count.

    # ---- skim-combo selection ----
    # "outer_pair" = the original spec: always close {oldest, newest} fill.
    # "best_combo" = compare combos of extreme orders and close whichever has
    # the best closure potential (lowest TP for longs): start from
    # {oldest, newest} and greedily add the next-deepest fill while each
    # addition still lowers the combo's weighted average - capped at
    # combo_max_orders fills (3 = the "first+last vs first+last-two" rule).
    combo_selection: str = "outer_pair"
    combo_max_orders: int = 3

    # ---- safety-order recycling ----
    # When a PARTIAL skim closes 2-3 fills, reopen exactly ONE order: at the
    # deepest closed rung's pre-calculated price. That deep, large fill is
    # the engine that drags the oldest expensive fills out profitably - so
    # re-arming it lets every down-and-up wave dispose of one more old fill.
    # The refill passes the same max_exposure_per_coin_usd gate as any SO.
    # NOTE: this trades away monotone exposure wind-down (the cap becomes
    # the safety guarantee) and a wavy coin's deal may stay open far longer.
    recycle_last_so: bool = False

    # ---- market regime brake ----
    # Alt waves correlate in a market-wide dump: if the reference pair (BTC)
    # is down more than the threshold over 24h, pause NEW base orders
    # portfolio-wide. Existing deals keep managing (SOs, skims, recycles) -
    # only fresh deal starts are gated, to avoid opening 10 new ladders into
    # a crash and freezing every slot at once.
    regime_brake_enabled: bool = False
    regime_brake_btc_drop_perc: float = 5.0
    regime_reference_pair: str = "BTC/USDT"

    # ---- deal lifecycle (DESIGN.md section 1-3) ----
    # A deal ages through phases; phases change EXIT behaviour only. All
    # boundaries are in the coin's own WAVE PERIODS (published by the
    # sidecar), not clock hours - a coin with 6h waves gets more clock time
    # per phase than a coin with 2h waves. Disabled = pure Wave Rider.
    lifecycle_enabled: bool = False
    phase_order: str = "regime"      # "wr,grid" | "grid,wr" | "regime"
    #   "regime": decided per deal at grace failure - healthy market ->
    #   Wave Rider first (waves likely); regime brake active -> grid first
    #   (continued fall likely: harvest easy inventory, hold SO powder).
    grace_waves: float = 3.0         # phase A: DCA full-close TP only
    winddown_waves: float = 6.0      # boundary between phase B and C
    decision_waves: float = 12.0     # entering phase D
    decision_wait_waves: float = 6.0 # D deliberation window per cycle
    wave_period_fallback_hours: float = 4.0  # when sidecar has no data
    grid_margin_perc: float = 0.5    # sell-only grid: exit at fill price + this %
    phase_d_loss_threshold_perc: float = 15.0  # rule 1: close if loss <= this
    phase_d_min_wave_score: float = 2.0        # rule 2: extend if score >= this
    phase_d_max_extensions: int = 1            # rule 2: never extend more

    # Drain fast-exit: a DRAINING coin whose position sits at/near breakeven
    # closes immediately (tag "drain_close") instead of waiting out a
    # lifecycle that may never trigger on a dead coin - the slot frees the
    # same hour, not days later. Max tolerated loss in %; negative disables.
    drain_fast_exit_max_loss_perc: float = -1.0

    # ---- capital-safety governors (CAPITAL_SAFETY.md, Tier 1) ----
    # P0-1 per-coin corridor brake: owns the -10%..-30% corridor where the
    # ladder otherwise buys into an accelerating fall. Wave-normalized
    # trigger ("fell further than this coin's own waves explain"), plus an
    # absolute floor for tiny-amplitude coins and an exposure trigger that
    # catches recycling buildup. Once latched the deal is SELL-ONLY until it
    # fully closes - no unbrake, no re-arming into the fall.
    coin_brake_enabled: bool = False
    coin_brake_wave_mult: float = 1.5      # x amplitude -> thesis-break level
    coin_brake_floor_perc: float = 12.0    # min drawdown before the price trigger fires
    coin_brake_exposure_frac: float = 0.6  # brake at this fraction of the per-coin cap

    # P0-2 crash freeze: extends the regime brake to OPEN deals - while
    # frozen, no buys anywhere (SOs/recycles included) and every open deal
    # is forced to sell-only grid. Hysteresis: freeze at
    # regime_brake_btc_drop_perc, unfreeze only past the shallower level
    # AND after a minimum dwell, so the coarse signal cannot flap.
    crash_freeze_enabled: bool = False
    regime_unfreeze_btc_drop_perc: float = 2.0
    regime_min_freeze_hours: float = 6.0

    # P1-1 aggregate exposure governor: portfolio-wide deployment ceiling as
    # % of wallet, checked before every buy. Guarantees a cash reserve by
    # construction. 0 or negative = disabled.
    max_aggregate_exposure_pct: float = 0.0

    # ---- slot parking ----
    # Deals that can NEVER buy again (corridor-braked, draining, or
    # decision-age) stop consuming a trading slot: the pair list grows by
    # the parked count (sidecar-side, capped + gated) while THIS gate keeps
    # the number of fresh (buy-capable) deals at max_coins. Long holds wind
    # down in the background without blocking opportunities.
    parking_enabled: bool = False

    # Reserve exclusion (Ajay's design): parked capital stops counting
    # against the working budget - the reserve underwrites the workout
    # bags so post-crash capacity stays fully powered. Bounds: exemption
    # capped at this % of wallet (worst case ceiling+cap deployed, hard
    # floor of the remainder that NO code path can touch), and it stays
    # inactive until the crash freeze has been released for the re-arm
    # dwell (never fuels a falling market). 0 disables.
    parked_exclusion_cap_pct: float = 0.0
    parked_exclusion_rearm_hours: float = 6.0

    # ---- dynamic per-coin ladder (Ajay's stage-2B experiment) ----
    # Rung spacing and take-profit computed from THIS coin's measured wave
    # amplitude at deal start (spacing = mult x amplitude, clamped), then
    # FROZEN for the deal - per-coin geometry, still pre-calculated.
    dynamic_ladder_enabled: bool = False
    dynamic_spacing_mult: float = 0.5   # rung gap = this x amplitude%
    dynamic_tp_mult: float = 0.5        # take-profit = this x amplitude%
    dynamic_min_perc: float = 0.8       # clamp floor for both
    dynamic_max_perc: float = 5.0       # clamp ceiling for both

    # This port is long-only: Binance spot cannot short. The spec's short mode
    # would need a futures/margin config and is intentionally not wired up here.
    is_long: bool = True

    # ================= FREQTRADE PLUMBING =================
    timeframe = "5m"

    # All exits are managed by the skim logic below. ROI is set unreachably
    # high and the framework stoploss unreachably low, so neither ever fires -
    # the spec has NO stop-loss ("non-renewal instead of forced exits").
    minimal_roi = {"0": 100}
    stoploss = -0.99
    trailing_stop = False
    use_exit_signal = False

    # Required for safety orders (positive return) and partial skim exits
    # (negative return) to be possible at all. -1 = no framework-side limit;
    # the real ladder-length limit is max_safety_orders (config-overridable),
    # enforced in adjust_trade_position.
    position_adjustment_enable = True
    max_entry_position_adjustment = -1

    process_only_new_candles = True
    can_short = False
    # One week of 5m candles: enough history to estimate wave period/score
    # in-strategy when the sidecar's state file is absent (backtesting).
    startup_candle_count: int = 2016

    # Lines drawn on the FreqUI price chart (columns set in
    # populate_indicators from the live deal ledger):
    #   overall_avg   - weighted average of ALL open fills (green)
    #   pair_avg      - weighted average of the outer skim combo (blue)
    #   tp_price      - skim take-profit level for that combo (cyan)
    #   next_so_price - next projected safety-order rung (amber)
    #   phase ribbon  - one color-coded strip in a small pane: gray = grace,
    #                   blue = wave rider, amber = grid, red = decision.
    #                   Computed per candle from deal age, so phase
    #                   TRANSITIONS are visible at the exact candle.
    # Position lines draw only from the deal's open candle onward, so
    # scrolling into pre-deal history lets the y-axis fit candles alone.
    # Deliberately no higher-timeframe overlays: wide series force FreqUI's
    # auto-fitted y-axis to span their full range and squash the candles.
    plot_config = {
        "main_plot": {
            "next_so_price": {"color": "#ffeb3b"},   # yellow: next SO rung
            "overall_avg": {"color": "#00e5ff"},     # cyan: whole-position avg
            "tp_price": {"color": "#4caf50"},        # green: ARMED exit target
            "tp_fill_1": {"color": "#e91e63"},   # magenta: every order the
            "tp_fill_2": {"color": "#e91e63"},   #   CURRENTLY ARMED exit will
            "tp_fill_3": {"color": "#e91e63"},   #   close - all fills in grace,
            "tp_fill_4": {"color": "#e91e63"},   #   the 1-3 combo in wave-riding,
            "tp_fill_5": {"color": "#e91e63"},   #   each eligible fill in
            "tp_fill_6": {"color": "#e91e63"},   #   grid/lockdown modes
        },
        "subplots": {
            "quality": {
                "wave_score": {"color": "#00bcd4"},
                "quality_floor": {"color": "#78909c"},
            },
            "phase": {
                "phase_grace": {"color": "#607d8b", "type": "bar"},
                "phase_wr": {"color": "#2196f3", "type": "bar"},
                "phase_grid": {"color": "#ffc107", "type": "bar"},
                "phase_decision": {"color": "#9c27b0", "type": "bar"},
                "phase_override": {"color": "#b71c1c", "type": "bar"},
            },
        },
    }

    def bot_start(self, **kwargs) -> None:
        # Pull overrides from the "wave_rider" section of config.json.
        # This runs on bot start AND on FreqUI's "Reload Config".
        overrides = self.config.get("wave_rider", {})
        self._fresh_slots = int(self.config.get("wave_rider", {}).get("max_coins", 10))
        self._quality_floor = float(self.config.get("wave_rider", {}).get("min_active_wave_score", 0))
        for key in (
            "take_profit_perc", "base_order_size_usd", "safety_order_size_usd",
            "max_safety_orders", "safety_order_price_deviation_perc",
            "safety_order_volume_scale", "safety_order_price_step_scale",
            "max_exposure_per_coin_usd", "max_deal_restarts",
            "combo_selection", "combo_max_orders", "recycle_last_so",
            "regime_brake_enabled", "regime_brake_btc_drop_perc",
            "regime_reference_pair",
            "lifecycle_enabled", "phase_order", "grace_waves",
            "winddown_waves", "decision_waves", "decision_wait_waves",
            "wave_period_fallback_hours", "grid_margin_perc",
            "phase_d_loss_threshold_perc", "phase_d_min_wave_score",
            "phase_d_max_extensions", "drain_fast_exit_max_loss_perc",
            "coin_brake_enabled", "coin_brake_wave_mult",
            "coin_brake_floor_perc", "coin_brake_exposure_frac",
            "crash_freeze_enabled", "regime_unfreeze_btc_drop_perc",
            "regime_min_freeze_hours", "max_aggregate_exposure_pct",
            "parking_enabled",
        ):
            if key in overrides:
                setattr(self, key, overrides[key])

    # ================= LADDER MATH (ladder.py of the reference, 1:1) =================

    def _stepped_deviation_percent(self, so_index: int,
                                   dev_perc: float = None) -> float:
        """Cumulative % distance of SO `so_index` (1-based) from the BO price."""
        if so_index <= 0:
            return 0.0
        base_dev = dev_perc if dev_perc else self.safety_order_price_deviation_perc
        total = 0.0
        for step in range(1, so_index + 1):
            total += base_dev * (
                self.safety_order_price_step_scale ** (step - 1)
            )
        return total

    def _so_trigger_price(self, so_index: int, base_price: float,
                          dev_perc: float = None) -> float:
        dev = self._stepped_deviation_percent(so_index, dev_perc)
        if self.is_long:
            return base_price * (1 - dev / 100.0)
        return base_price * (1 + dev / 100.0)

    def _so_size_usd(self, so_index: int) -> float:
        return self.safety_order_size_usd * (
            self.safety_order_volume_scale ** (so_index - 1)
        )

    # ================= PER-TRADE LEDGER (deal.py state, in trade custom data) ========
    #
    # open_fills:    ordered list (oldest first) of {"id", "price", "qty", "size_usd"}
    # base_price:    the BO fill price the whole ladder is calculated from
    # next_so_index: 1-based pointer to the next unfilled ladder rung
    # pending_skim:  fill-ids we asked to exit, matched up when the sell fills

    def _get_fills(self, trade: Trade) -> list:
        return self._cd_list(trade, "open_fills")


    # Custom-data coercion: freqtrade's backtesting wrapper can hand values
    # back as JSON strings (None -> 'null'), so never trust the raw type.
    def _cd_int(self, trade: Trade, key: str, default: int) -> int:
        value = trade.get_custom_data(key, default=default)
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def _cd_float(self, trade: Trade, key: str):
        value = trade.get_custom_data(key, default=None)
        try:
            value = float(value)
            return value if value > 0 else None
        except (TypeError, ValueError):
            return None

    def _cd_list(self, trade: Trade, key: str) -> list:
        value = trade.get_custom_data(key, default=[])
        return value if isinstance(value, list) else []

    def _exposure_usd(self, fills: list) -> float:
        return sum(f["size_usd"] for f in fills)

    def _has_open_orders(self, trade: Trade) -> bool:
        return any(o.ft_is_open for o in trade.orders)

    def _deal_dev_perc(self, trade: Trade) -> float:
        """This deal's rung spacing % (dynamic per-coin if set at BO)."""
        value = self._cd_float(trade, "deal_dev_perc")
        return value if value else self.safety_order_price_deviation_perc

    def _deal_tp_perc(self, trade: Trade) -> float:
        """This deal's take-profit % (dynamic per-coin if set at BO)."""
        value = self._cd_float(trade, "deal_tp_perc")
        return value if value else self.take_profit_perc

    def _fill_rung_index(self, fill: dict) -> int:
        """Ladder rung a fill came from, parsed from its id ('SO7', 'SO7R2'
        for a recycled refill of rung 7). The base order ('BO') is rung 0."""
        fid = fill["id"]
        if not fid.startswith("SO"):
            return 0
        digits = ""
        for ch in fid[2:]:
            if not ch.isdigit():
                break
            digits += ch
        return int(digits) if digits else 0

    def _select_skim_combo(self, fills: list) -> list:
        """
        Which open fills should the next skim close?

        "outer_pair" (spec default): always {oldest, newest}.
        "best_combo": start from {oldest, newest}, then greedily add the
        next-deepest fill while each addition still improves closure
        potential - i.e. moves the combo's weighted average toward price
        (down for longs), which lowers its TP so it closes sooner. A fill
        improves the average exactly when its price is beyond the current
        combo average, so this greedy walk finds the minimum-TP combo.
        Capped at combo_max_orders fills (3 = "pair vs pair+second-last").
        The oldest fill is ALWAYS included - every skim disposes of the
        worst inventory first, so the book improves with each wave.
        """
        if len(fills) == 1:
            return [fills[0]]
        combo = [fills[0], fills[-1]]
        if self.combo_selection != "best_combo":
            return combo
        i = len(fills) - 2
        while i >= 1 and len(combo) < self.combo_max_orders:
            candidate = fills[i]
            combo_avg = (sum(f["price"] * f["qty"] for f in combo)
                         / sum(f["qty"] for f in combo))
            improves = (candidate["price"] < combo_avg) if self.is_long \
                else (candidate["price"] > combo_avg)
            if not improves:
                break
            combo.append(candidate)
            i -= 1
        return combo

    # ================= ENTRIES =================

    @informative("5m", "BTC/USDT")
    def populate_indicators_ref(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # Reference feed for the regime signal (merged into every pair as
        # ref_btc_usdt_5m). Live mode ignores this and uses the ticker.
        dataframe["ref"] = dataframe["close"]
        return dataframe

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # Chart lines for FreqUI (see plot_config above), computed from the
        # live deal ledger. Values refresh when a new candle is analysed, so
        # after a fill the lines catch up within one candle.
        for col in ("overall_avg", "tp_price", "next_so_price",
                    "wave_score", "quality_floor",
                    "tp_fill_1", "tp_fill_2", "tp_fill_3",
                    "tp_fill_4", "tp_fill_5", "tp_fill_6",
                    "phase_grace", "phase_wr", "phase_grid", "phase_decision",
                    "phase_override"):
            dataframe[col] = float("nan")

        # Wave stats needed in every runmode (lifecycle boundaries in
        # backtests have no sidecar to lean on).
        self._update_wave_stats(dataframe, metadata["pair"])

        # Regime signal column for backtests: BTC's rolling 24h %% change,
        # from the merged reference feed. Live uses the ticker instead.
        ref_cols = [c for c in dataframe.columns
                    if "ref" in c and c != "ref_change_24h"]
        ref_col = ref_cols[0] if ref_cols else None
        if ref_col:
            candles_per_day = int(24 * 60 / timeframe_to_minutes(self.timeframe))
            dataframe["ref_change_24h"] = \
                dataframe[ref_col].pct_change(candles_per_day) * 100.0

        # Quality pane: this coin's current wave score vs the rotation
        # floor - visible for every listed coin, position or not.
        score = self._pair_wave_score(metadata["pair"])
        if score is not None:
            dataframe["wave_score"] = score
        if getattr(self, "_quality_floor", 0) > 0:
            dataframe["quality_floor"] = self._quality_floor

        if not (self.dp and self.dp.runmode.value in ("live", "dry_run")):
            return dataframe  # no live ledger to draw in backtests

        trades = Trade.get_trades_proxy(pair=metadata["pair"], is_open=True)
        if not trades:
            return dataframe
        trade = trades[0]

        # Everything below draws from the deal's open candle onward only -
        # pre-deal history stays clean and the y-axis can fit bare candles
        # when scrolled back.
        since_open = dataframe["date"] >= trade.open_date_utc

        # Phase ribbon, historically accurate: phase is a pure function of
        # deal age in wave periods, so each candle since open gets its
        # phase color; transitions appear at the exact candle they happened.
        if self.lifecycle_enabled:
            period_h = self._wave_period_hours(trade.pair)
            plan = trade.get_custom_data("phase_plan", default=None)                 or (self.phase_order if "," in self.phase_order else "wr,grid")
            try:
                first, second = str(plan).split(",")
            except ValueError:
                first, second = "wr", "grid"
            ages = (dataframe["date"] - trade.open_date_utc).dt.total_seconds() \
                / 3600.0 / period_h

            def phase_of(age: float):
                if age < 0:
                    return None
                if age < self.grace_waves:
                    return "grace"
                if age >= self.decision_waves:
                    return "decision"
                return first if age < self.winddown_waves else second

            phases = ages.map(phase_of)
        else:
            phases = since_open.map(lambda in_deal: "wr" if in_deal else None)
        # Governor overrides paint on top of the lifecycle phase: a braked
        # deal behaves as sell-only grid no matter what phase says.
        braked_at = trade.get_custom_data("coin_braked_at", default=None)
        if braked_at:
            try:
                braked_dt = datetime.fromisoformat(braked_at)
                phases = phases.mask(dataframe["date"] >= braked_dt, "override")
            except ValueError:
                pass
        if self._frozen:
            phases.iloc[-1] = "override"
        for name in PHASE_NAMES:
            dataframe.loc[phases == name, f"phase_{name}"] = 1.0

        fills = self._get_fills(trade)
        if not fills:
            return dataframe

        total_qty = sum(f["qty"] for f in fills)
        blended_avg = sum(f["price"] * f["qty"] for f in fills) / total_qty
        dataframe.loc[since_open, "overall_avg"] = blended_avg

        # The cyan tp_price line always shows the target that is ACTUALLY
        # armed in the deal's current phase - never a dormant one:
        #   grace    -> blended average of ALL fills + TP%
        #   wr       -> the skim combo's average + TP% (blue = combo avg)
        #   grid/D   -> the nearest eligible per-fill breakeven+ exit level
        current_phase = self._deal_phase(trade, datetime.now(timezone.utc))
        tp_factor = (1 + self.take_profit_perc / 100.0) if self.is_long \
            else (1 - self.take_profit_perc / 100.0)

        if current_phase == "grace":
            dataframe.loc[since_open, "tp_price"] = blended_avg * tp_factor
        elif current_phase == "wr":
            combo = self._select_skim_combo(fills)
            combo_avg = (sum(f["price"] * f["qty"] for f in combo)
                         / sum(f["qty"] for f in combo))
            for i, f in enumerate(combo[:3], 1):
                dataframe.loc[since_open, f"combo_fill_{i}"] = f["price"]
            dataframe.loc[since_open, "tp_price"] = combo_avg * tp_factor
        else:  # grid / decision: sell-only liquidation levels
            margin = self.grid_margin_perc / 100.0
            eligible = list(fills)
            if current_phase == "grid" and len(fills) > 1:
                deepest = min(fills, key=lambda f: f["price"]) if self.is_long \
                    else max(fills, key=lambda f: f["price"])
                eligible = [f for f in fills if f["id"] != deepest["id"]]
            levels = [f["price"] * (1 + margin) if self.is_long
                      else f["price"] * (1 - margin) for f in eligible]
            if levels:
                nearest = min(levels) if self.is_long else max(levels)
                dataframe.loc[since_open, "tp_price"] = nearest

        # Next projected SO - only in phases that are allowed to buy.
        if current_phase in ("grace", "wr"):
            base_price = self._cd_float(trade, "base_price")
            refills = sorted(self._cd_list(trade, "refill_rungs"))
            next_so_index = self._cd_int(trade, "next_so_index", 1)
            if base_price:
                if refills and current_phase == "wr":
                    dataframe.loc[since_open, "next_so_price"] = \
                        self._so_trigger_price(refills[0], base_price)
                elif next_so_index <= self.max_safety_orders:
                    dataframe.loc[since_open, "next_so_price"] = \
                        self._so_trigger_price(next_so_index, base_price)

        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # Spec rule 1: no entry signal - a flat pair always starts a new deal.
        # Freqtrade only ever acts on the newest candle's signal, so in
        # live/dry-run the signal is set on that candle alone - behaviour is
        # identical, but the chart shows one marker at the live edge instead
        # of a triangle on every candle. Backtesting still needs the signal
        # on every row.
        if self.dp and self.dp.runmode.value in ("live", "dry_run"):
            dataframe["enter_long"] = 0
            dataframe.loc[dataframe.index[-1], "enter_long"] = 1
        else:
            dataframe["enter_long"] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # No signal-based exits: skim-closes in adjust_trade_position are the
        # only exit path, per spec.
        return dataframe

    def custom_stake_amount(self, pair: str, current_time: datetime,
                            current_rate: float, proposed_stake: float,
                            min_stake: Optional[float], max_stake: float,
                            leverage: float, entry_tag: Optional[str],
                            side: str, **kwargs) -> float:
        # The BO is always base_order_size_usd (exchange minimum permitting).
        stake = self.base_order_size_usd
        if min_stake:
            stake = max(stake, min_stake)
        return min(stake, max_stake)

    def _pairlist_state(self) -> dict:
        """pairlist_state.json, maintained by scripts/pairlist_updater.py."""
        state_file = Path(self.config["user_data_dir"]) / "pairlist_state.json"
        try:
            return json.loads(state_file.read_text())
        except (OSError, ValueError):
            return {}

    def _pair_joined_at(self, pair: str) -> Optional[datetime]:
        """
        When did this pair last join the active list? Returns None when the
        state file/pair is absent - the restart gate then falls back to a
        lifetime count, which is the static-pairlist spec behaviour.
        """
        joined_iso = self._pairlist_state().get("active", {}).get(pair)
        try:
            return datetime.fromisoformat(joined_iso) if joined_iso else None
        except ValueError:
            return None

    def _is_parked(self, trade: Trade, current_time: datetime) -> bool:
        """A parked deal can never buy again: braked, draining, or old
        enough to be in the decision stage. Parked deals don't count
        against the fresh-deal slots."""
        if self._cd_int(trade, "coin_braked", 0):
            return True
        if self._is_draining(trade.pair):
            return True
        return self.lifecycle_enabled and             self._deal_age_waves(trade, current_time) >= self.decision_waves

    def _is_draining(self, pair: str) -> bool:
        """
        Rotation drain (marked by the sidecar): this coin is being wound
        down - recycling stops, skims monotonically empty the deal, and the
        coin retires when flat, freeing its slot for a fresh candidate.
        """
        return pair in self._pairlist_state().get("draining", {})

    def informative_pairs(self):
        # Register the reference pair so the regime signal works in
        # backtesting too (live uses the ticker; backtests use candles).
        # Read the CONFIG directly: this hook can run before bot_start
        # applies the wave_rider overrides, and with class defaults (flags
        # off) the reference data was never requested - which silently
        # disabled the crash freeze in the first two tail sweeps.
        wr = self.config.get("wave_rider", {})
        if wr.get("regime_brake_enabled", self.regime_brake_enabled)                 or wr.get("crash_freeze_enabled", self.crash_freeze_enabled):
            ref = wr.get("regime_reference_pair", self.regime_reference_pair)
            return [(ref, self.timeframe)]
        return []

    def _reference_change_24h(self, current_time: Optional[datetime] = None,
                              pair: Optional[str] = None) -> Optional[float]:
        """Reference pair's 24h %% change. Live: exchange ticker. Backtests:
        the ref_change_24h column merged into every traded pair's dataframe
        via the BTC informative feed (the only data path backtesting
        actually supports - two earlier attempts read paths that are empty
        in backtest mode and silently disabled the crash freeze)."""
        if self.dp and self.dp.runmode.value in ("live", "dry_run"):
            try:
                return self.dp.ticker(self.regime_reference_pair).get("percentage")
            except Exception:
                return None
        if not pair:
            return None
        try:
            df, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        except Exception:
            return None
        if df is None or len(df) == 0 or "ref_change_24h" not in df.columns:
            return None
        if current_time is not None:
            df = df[df["date"] <= current_time]
        if len(df) == 0:
            return None
        value = df["ref_change_24h"].iloc[-1]
        try:
            value = float(value)
        except (TypeError, ValueError):
            return None
        return None if value != value else value  # NaN guard



    def _market_in_crash(self, current_time: Optional[datetime] = None,
                         pair: Optional[str] = None) -> bool:
        """Regime brake: is the reference pair down past the threshold over
        24h? Fails open (no brake) if the signal can't be computed."""
        change = self._reference_change_24h(current_time, pair)
        return change is not None and change <= -abs(self.regime_brake_btc_drop_perc)

    # ============ CAPITAL-SAFETY GOVERNORS (CAPITAL_SAFETY.md) ============

    def _coin_braked(self, trade: Trade, current_rate: float, fills: list) -> bool:
        """
        P0-1 per-coin corridor brake. Latches (until the deal fully closes)
        when the coin fell further than its own waves explain, or when
        deployed exposure crosses the fraction trigger. While latched the
        deal is sell-only.
        """
        if not self.coin_brake_enabled:
            return False
        if self._cd_int(trade, "coin_braked", 0):
            return True  # latched - no unbrake until the deal closes

        base_price = self._cd_float(trade, "base_price")
        if not base_price:
            return False
        if self.is_long:
            drawdown_perc = 100.0 * (base_price - current_rate) / base_price
        else:
            drawdown_perc = 100.0 * (current_rate - base_price) / base_price

        amplitude = self._pair_amplitude(trade.pair) or 0.0
        # The floor keeps tiny-amplitude coins from braking on trivial dips;
        # the wave multiple keeps big-wave coins from being strangled.
        price_threshold = max(self.coin_brake_wave_mult * amplitude,
                              self.coin_brake_floor_perc)
        exposure = self._exposure_usd(fills)
        exposure_threshold = self.coin_brake_exposure_frac * self.max_exposure_per_coin_usd

        reason = None
        if drawdown_perc > price_threshold:
            reason = (f"drawdown {drawdown_perc:.1f}% > {price_threshold:.1f}% "
                      f"({self.coin_brake_wave_mult}x wave {amplitude:.1f}%)")
        elif exposure > exposure_threshold:
            reason = f"exposure ${exposure:.0f} > ${exposure_threshold:.0f}"
        if reason is None:
            return False

        trade.set_custom_data("coin_braked", 1)
        trade.set_custom_data("coin_braked_at",
                              datetime.now(timezone.utc).isoformat())
        logger.info(f"{trade.pair}: CORRIDOR BRAKE latched ({reason}) - "
                    f"sell-only until this deal closes")
        return True

    # P0-2 crash-freeze state (portfolio-wide, hysteresis)
    _frozen: bool = False
    _freeze_started: Optional[datetime] = None
    _freeze_released: Optional[datetime] = None

    def _crash_frozen(self, current_time: datetime,
                      pair: Optional[str] = None) -> bool:
        """
        P0-2: while frozen, no buys anywhere and open deals go sell-only.
        Freezes at regime_brake_btc_drop_perc; unfreezes only when the 24h
        change recovers past regime_unfreeze_btc_drop_perc AND the freeze
        has dwelt at least regime_min_freeze_hours.
        """
        if not self.crash_freeze_enabled:
            return False
        change = self._reference_change_24h(current_time, pair)
        if change is None:
            return self._frozen  # no data: hold current state, fail safe

        if not self._frozen:
            if change <= -abs(self.regime_brake_btc_drop_perc):
                self._frozen = True
                self._freeze_started = current_time
                logger.info(f"CRASH FREEZE engaged ({self.regime_reference_pair} "
                            f"{change:+.1f}%/24h) - all buys halted, open deals sell-only")
        else:
            dwelt = (current_time - self._freeze_started).total_seconds() / 3600.0 \
                if self._freeze_started else 999.0
            if dwelt >= self.regime_min_freeze_hours \
                    and change >= -abs(self.regime_unfreeze_btc_drop_perc):
                self._frozen = False
                self._freeze_released = current_time
                logger.info(f"CRASH FREEZE released ({self.regime_reference_pair} "
                            f"{change:+.1f}%/24h after {dwelt:.1f}h) - buys resume")
        return self._frozen

    def _aggregate_exposure_ok(self, additional_usd: float,
                               current_time: Optional[datetime] = None) -> bool:
        """
        P1-1: portfolio deployment ceiling. True if adding `additional_usd`
        keeps total open exposure within max_aggregate_exposure_pct of the
        wallet - a cash reserve exists by construction.
        """
        if self.max_aggregate_exposure_pct <= 0:
            return True
        open_trades = Trade.get_trades_proxy(is_open=True)
        total = sum((t.stake_amount or 0.0) for t in open_trades)
        try:
            wallet = float(self.wallets.get_total(self.config["stake_currency"]))
        except Exception:
            wallet = float(self.config.get("dry_run_wallet", 10000))
        if wallet <= 0:
            wallet = float(self.config.get("dry_run_wallet", 10000))
        # Reserve exclusion: parked (never-buy-again) capital is exempted
        # up to the cap, only when not frozen and past the re-arm dwell.
        if (self.parking_enabled and self.parked_exclusion_cap_pct > 0
                and current_time is not None and not self._frozen):
            dwelt_ok = self._freeze_released is None or (
                (current_time - self._freeze_released).total_seconds() / 3600.0
                >= self.parked_exclusion_rearm_hours)
            if dwelt_ok:
                parked_stake = sum(
                    (t.stake_amount or 0.0) for t in open_trades
                    if self._is_parked(t, current_time))
                total -= min(parked_stake,
                             self.parked_exclusion_cap_pct / 100.0 * wallet)
        return (total + additional_usd) <= self.max_aggregate_exposure_pct / 100.0 * wallet

    # ================= DEAL LIFECYCLE (DESIGN.md sections 1-3) =================

    # In-strategy wave stats, refreshed each time populate_indicators runs.
    # Fallback chain everywhere: sidecar state file (live) -> this cache
    # (backtesting / sidecar down) -> configured constant.
    _wave_stats_cache: dict = {}

    def _update_wave_stats(self, dataframe: DataFrame, pair: str) -> None:
        """
        Same math as the sidecar's score_symbol, computed from the bot's own
        candles aggregated into ~4h blocks. Backtest limitation (documented
        in DESIGN.md): populate_indicators runs once over the whole window in
        backtesting, so this estimate is static per window rather than
        rolling - wave periods drift slowly, so this is acceptable for the
        stage-1 matrix.
        """
        tf_minutes = timeframe_to_minutes(self.timeframe)
        step = max(1, round(240 / tf_minutes))  # candles per 4h block
        n_blocks = min(len(dataframe) // step, 42)
        if n_blocks < 6:
            return  # not enough history; callers fall back to the constant

        closes_raw = dataframe["close"].to_numpy()[-n_blocks * step:]
        highs_raw = dataframe["high"].to_numpy()[-n_blocks * step:]
        lows_raw = dataframe["low"].to_numpy()[-n_blocks * step:]

        closes, swings = [], []
        for i in range(n_blocks):
            lo = float(lows_raw[i * step:(i + 1) * step].min())
            hi = float(highs_raw[i * step:(i + 1) * step].max())
            closes.append(float(closes_raw[(i + 1) * step - 1]))
            mid = (hi + lo) / 2
            if mid > 0:
                swings.append((hi - lo) / mid)
        if not swings:
            return
        amplitude = 100.0 * sum(swings) / len(swings)

        path = sum(abs(closes[i] - closes[i - 1]) for i in range(1, len(closes)))
        trendiness = abs(closes[-1] - closes[0]) / path if path > 0 else 1.0

        direction_changes, prev_sign = 0, 0
        for i in range(1, len(closes)):
            diff = closes[i] - closes[i - 1]
            sign = 1 if diff > 0 else (-1 if diff < 0 else 0)
            if sign != 0 and prev_sign != 0 and sign != prev_sign:
                direction_changes += 1
            if sign != 0:
                prev_sign = sign
        block_hours = step * tf_minutes / 60.0
        total_hours = n_blocks * block_hours
        waves = max(direction_changes / 2.0, 1.0)
        period = min(max(total_hours / waves, block_hours), total_hours)

        self._wave_stats_cache[pair] = {
            "period": period,
            "score": amplitude * (1 - trendiness),
            "amplitude": amplitude,
        }

    def _wave_period_hours(self, pair: str) -> float:
        """This coin's typical down-and-up cycle length."""
        period = self._pairlist_state().get("wave_period_hours", {}).get(pair)
        try:
            period = float(period)
        except (TypeError, ValueError):
            period = None
        if period and period > 0:
            return period
        cached = self._wave_stats_cache.get(pair)
        if cached:
            return cached["period"]
        return self.wave_period_fallback_hours

    def _pair_wave_score(self, pair: str) -> Optional[float]:
        """Current wave score: sidecar first, in-strategy estimate second."""
        score = self._pairlist_state().get("scores", {}).get(pair)
        if score is not None:
            return score
        cached = self._wave_stats_cache.get(pair)
        return cached["score"] if cached else None

    def _pair_amplitude(self, pair: str) -> Optional[float]:
        """Raw wave amplitude % (unweighted): sidecar first, then cache."""
        amp = self._pairlist_state().get("amplitudes", {}).get(pair)
        try:
            amp = float(amp)
        except (TypeError, ValueError):
            amp = None
        if amp and amp > 0:
            return amp
        cached = self._wave_stats_cache.get(pair)
        return cached.get("amplitude") if cached else None

    def _deal_age_waves(self, trade: Trade, current_time: datetime) -> float:
        age_hours = (current_time - trade.open_date_utc).total_seconds() / 3600.0
        return age_hours / self._wave_period_hours(trade.pair)

    def _phase_plan(self, trade: Trade, current_time: Optional[datetime] = None) -> str:
        """
        B/C ordering for this deal, decided ONCE at grace failure and pinned
        in custom data (the plan must not flip-flop with the market later).
        """
        plan = trade.get_custom_data("phase_plan", default=None)
        if plan:
            return plan
        if self.phase_order == "regime":
            plan = "grid,wr" if (self.regime_brake_enabled and self._market_in_crash()) \
                else "wr,grid"
        else:
            plan = self.phase_order
        trade.set_custom_data("phase_plan", plan)
        return plan

    def _deal_phase(self, trade: Trade, current_time: datetime) -> str:
        """'grace' | 'wr' | 'grid' | 'decision' for this deal, by wave age."""
        if not self.lifecycle_enabled:
            return "wr"
        waves = self._deal_age_waves(trade, current_time)
        if waves < self.grace_waves:
            return "grace"
        if waves >= self.decision_waves:
            return "decision"
        first, second = self._phase_plan(trade, current_time).split(",")
        return first if waves < self.winddown_waves else second

    def confirm_trade_entry(self, pair: str, order_type: str, amount: float,
                            rate: float, time_in_force: str,
                            current_time: datetime, entry_tag: Optional[str],
                            side: str, **kwargs) -> bool:
        # Spec rule 4: restart limit. Completed deals live in the bot's
        # database as closed trades, so the count survives restarts. With the
        # dynamic pairlist, only deals closed since the pair JOINED the
        # active list count - a coin that retires and later returns starts a
        # fresh allowance. Only fresh deals are gated - never safety orders
        # on an already-open trade.
        has_open_trade = bool(Trade.get_trades_proxy(pair=pair, is_open=True))
        if not has_open_trade:
            # A draining coin must not start a fresh deal in the gap before
            # the sidecar's next cycle retires it.
            if self._is_draining(pair):
                return False
            # A RETIRED coin must not restart either: retirement clears the
            # draining mark a few minutes before the whitelist refresh
            # actually drops the pair - this closes that gap. A coin that
            # legitimately rejoins later is moved out of "retired" first.
            if pair in self._pairlist_state().get("retired", {}):
                return False
            # Regime brake: don't open new ladders into a market-wide crash.
            if self.regime_brake_enabled and self._market_in_crash(current_time, pair):
                return False
            # P0-2 crash freeze (hysteresis): stays blocked until the freeze
            # releases, even after the raw -5% signal fades.
            if self._crash_frozen(current_time, pair):
                return False
            # P1-1 aggregate governor: no new deal past the portfolio ceiling.
            if not self._aggregate_exposure_ok(self.base_order_size_usd, current_time):
                return False
            # Parking: fresh (buy-capable) deals stay capped at max_coins
            # even though the pair list is larger by the parked count.
            if self.parking_enabled:
                fresh = sum(
                    1 for t in Trade.get_trades_proxy(is_open=True)
                    if not self._is_parked(t, current_time))
                if fresh >= getattr(self, "_fresh_slots", 10):
                    return False
            closed = Trade.get_trades_proxy(pair=pair, is_open=False)
            joined = self._pair_joined_at(pair)
            if joined is not None:
                closed = [t for t in closed
                          if t.close_date_utc and t.close_date_utc >= joined]
            # A Phase D capitulation ends the coin's stint outright: no new
            # grace phase may open. (The sidecar retires it on its next
            # cycle; this gate closes the minutes-wide gap in between. A
            # coin that later REJOINS starts a fresh stint - its join date
            # is newer than the capitulation, so this gate releases.)
            # Capitulation OR drain-eviction ends the coin's stint outright.
            if any(t.exit_reason in ("phase_d_close", "drain_close")
                   for t in closed):
                return False
            if len(closed) >= self.max_deal_restarts:
                return False
        return True

    # ================= THE DEAL STATE MACHINE (spec rules 2, 3, 5) =================

    def adjust_trade_position(self, trade: Trade, current_time: datetime,
                              current_rate: float, current_profit: float,
                              min_stake: Optional[float], max_stake: float,
                              current_entry_rate: float, current_exit_rate: float,
                              current_entry_profit: float, current_exit_profit: float,
                              **kwargs):
        # Never stack orders: wait until the previous entry/exit has resolved,
        # so the ledger in custom data is always in sync with reality.
        if self._has_open_orders(trade):
            return None

        fills = self._get_fills(trade)
        if not fills:
            # BO placed but its fill hasn't been recorded yet (order_filled
            # runs right after the fill) - nothing to do this iteration.
            return None

        # Drain fast-exit: a draining coin at/near breakeven closes NOW.
        # Overrides every phase - zombie slots must not wait out a lifecycle
        # that may never trigger on a coin without waves.
        if self.drain_fast_exit_max_loss_perc >= 0 \
                and self._is_draining(trade.pair) \
                and current_profit >= -(self.drain_fast_exit_max_loss_perc / 100.0):
            trade.set_custom_data("pending_skim", [f["id"] for f in fills])
            trade.set_custom_data("pending_skim_recycle_rung", 0)
            return -trade.stake_amount, "drain_close"

        # P0-1 corridor brake: this coin fell past what its waves explain
        # (or exposure tripped) - sell-only liquidation until the deal
        # closes, regardless of lifecycle phase.
        if self._coin_braked(trade, current_rate, fills):
            return self._grid_exit_check(trade, fills, current_rate,
                                         reserve_deepest=False)

        # P0-2 crash freeze: market-wide dump - every open deal is
        # sell-only until the freeze releases. The grid only harvests
        # bounces; the freeze itself is the protection.
        if self._crash_frozen(current_time, trade.pair):
            return self._grid_exit_check(trade, fills, current_rate,
                                         reserve_deepest=False)

        # ---- lifecycle dispatch: which exit machinery runs depends on the
        # deal's age, measured in its coin's own wave periods ----
        phase = self._deal_phase(trade, current_time)

        # Narrate phase transitions (visible in logs and the log monitor).
        last_phase = trade.get_custom_data("last_phase", default="")
        if phase != last_phase:
            logger.info(
                f"{trade.pair}: lifecycle phase "
                f"{'started as' if not last_phase else last_phase + ' ->'} {phase} "
                f"(deal age {self._deal_age_waves(trade, current_time):.1f} waves, "
                f"wave period {self._wave_period_hours(trade.pair):.1f}h)")
            trade.set_custom_data("last_phase", phase)

        if phase == "grace":
            # Phase A: classic DCA - full-position TP on the blended average
            # of ALL fills; no skims yet. Fresh SOs keep filling below.
            return self._grace_check(trade, fills, current_rate,
                                     min_stake, max_stake, current_time)
        if phase == "grid":
            # Phase B/C (sell-only grid): liquidation ladder, no buys.
            return self._grid_exit_check(trade, fills, current_rate,
                                         reserve_deepest=True)
        if phase == "decision":
            # Phase D: no buys; grid exits keep peeling (reserve off -
            # everything sellable), and at the deadline the mechanical
            # close/extend decision runs.
            exit_request = self._grid_exit_check(trade, fills, current_rate,
                                                 reserve_deepest=False)
            if exit_request is not None:
                return exit_request
            return self._phase_d_decision(trade, fills, current_rate, current_time)

        # ---- phase "wr" - Spec rule 5a: skim-close check FIRST ----
        # The combo of extreme fills chosen by _select_skim_combo; a single
        # remaining fill is judged on its own.
        combo = self._select_skim_combo(fills)
        total_qty = sum(f["qty"] for f in combo)
        avg_price = sum(f["price"] * f["qty"] for f in combo) / total_qty

        deal_tp = self._deal_tp_perc(trade)
        if self.is_long:
            tp_price = avg_price * (1 + deal_tp / 100.0)
            tp_hit = current_rate >= tp_price
        else:
            tp_price = avg_price * (1 - deal_tp / 100.0)
            tp_hit = current_rate <= tp_price

        if tp_hit:
            trade.set_custom_data("pending_skim", [f["id"] for f in combo])

            # Recycling: a PARTIAL skim closes 2-3 fills but reopens only
            # ONE - the deepest closed rung goes on the refill queue (armed
            # here, queued when the exit actually fills in order_filled).
            recycle_rung = None
            if self.recycle_last_so and len(combo) < len(fills) \
                    and not self._is_draining(trade.pair):
                deepest = min(combo, key=lambda f: f["price"]) if self.is_long \
                    else max(combo, key=lambda f: f["price"])
                rung = self._fill_rung_index(deepest)
                recycle_rung = rung if rung > 0 else None  # never recycle the BO
            trade.set_custom_data("pending_skim_recycle_rung", recycle_rung or 0)

            if len(combo) >= len(fills):
                # Closing everything that's left - exit the whole remaining
                # position so no dust is left behind (spec rule 4 full close).
                return -trade.stake_amount, "skim_full_close"
            qty_to_sell = min(total_qty, trade.amount)
            return -(qty_to_sell * current_rate), "skim_close"

        # Deferred-rung crash guard: in a grid-first plan, WR inherits the
        # rungs the grid phase left untriggered; never bulk-deploy maximum
        # counterweight into a market-wide crash (DESIGN.md section 1).
        if self.lifecycle_enabled and self._phase_plan(trade) == "grid,wr" \
                and self.regime_brake_enabled and self._market_in_crash():
            return None

        return self._safety_order_check(trade, fills, current_rate,
                                        min_stake, max_stake, allow_refills=True,
                                        current_time=current_time)

    # ---- lifecycle phase helpers ----

    def _grace_check(self, trade: Trade, fills: list, current_rate: float,
                     min_stake: Optional[float], max_stake: float,
                     current_time: Optional[datetime] = None):
        """Phase A exit: one full-position TP on the blended average."""
        total_qty = sum(f["qty"] for f in fills)
        avg_price = sum(f["price"] * f["qty"] for f in fills) / total_qty
        deal_tp = self._deal_tp_perc(trade)
        if self.is_long:
            tp_hit = current_rate >= avg_price * (1 + deal_tp / 100.0)
        else:
            tp_hit = current_rate <= avg_price * (1 - deal_tp / 100.0)
        if tp_hit:
            trade.set_custom_data("pending_skim", [f["id"] for f in fills])
            trade.set_custom_data("pending_skim_recycle_rung", 0)
            return -trade.stake_amount, "grace_full_close"
        return self._safety_order_check(trade, fills, current_rate,
                                        min_stake, max_stake, allow_refills=False,
                                        current_time=current_time)

    def _safety_order_check(self, trade: Trade, fills: list, current_rate: float,
                            min_stake: Optional[float], max_stake: float,
                            allow_refills: bool,
                            current_time: Optional[datetime] = None):
        """Spec rule 5b / rule 2: recycled refills first, then the fresh rung."""
        base_price = self._cd_float(trade, "base_price")
        if not base_price:
            return None  # defensive: ledger not initialised yet

        # Recycled rungs first: they always sit shallower (nearer the price)
        # than any fresh rung, so a falling price reaches them first. Same
        # pre-calculated price, same cap gate, one order per iteration.
        deal_dev = self._deal_dev_perc(trade)
        refill_rungs = sorted(self._cd_list(trade, "refill_rungs"))
        if refill_rungs and allow_refills and not self._is_draining(trade.pair):
            rung = refill_rungs[0]
            rung_price = self._so_trigger_price(rung, base_price, deal_dev)
            rung_hit = (current_rate <= rung_price) if self.is_long \
                else (current_rate >= rung_price)
            if rung_hit:
                rung_size = self._so_size_usd(rung)
                so_stake = max(rung_size, min_stake) if min_stake else rung_size
                so_stake = min(so_stake, max_stake)
                # Cap check on the FINAL stake (after the exchange-minimum
                # bump), so the bump can never push past the ceiling.
                if so_stake <= self.max_exposure_per_coin_usd - self._exposure_usd(fills) \
                        and self._aggregate_exposure_ok(so_stake, current_time):
                    trade.set_custom_data("pending_recycle", rung)
                    return so_stake, f"so_{rung}_recycle"

        next_so_index = self._cd_int(trade, "next_so_index", 1)
        if next_so_index > self.max_safety_orders:
            return None  # ladder exhausted

        rung_price = self._so_trigger_price(next_so_index, base_price, deal_dev)
        if self.is_long:
            rung_hit = current_rate <= rung_price
        else:
            rung_hit = current_rate >= rung_price
        if not rung_hit:
            return None

        # Exposure cap gate (spec rule 2): if this rung doesn't fit under the
        # per-coin ceiling, WAIT. Do not resize, do not skip, do not advance
        # the pointer. A later skim that frees capital lets it fire, provided
        # price is still at/through the rung. Checked on the FINAL stake
        # (after the exchange-minimum bump) so the bump can never overshoot.
        so_stake = self._so_size_usd(next_so_index)
        if min_stake:
            so_stake = max(so_stake, min_stake)
        so_stake = min(so_stake, max_stake)
        if so_stake > self.max_exposure_per_coin_usd - self._exposure_usd(fills):
            return None
        if not self._aggregate_exposure_ok(so_stake, current_time):
            return None  # P1-1: portfolio ceiling - wait like a cap-blocked rung

        trade.set_custom_data("pending_recycle", 0)
        return so_stake, f"so_{next_so_index}"

    def _grid_exit_check(self, trade: Trade, fills: list, current_rate: float,
                         reserve_deepest: bool):
        """
        Sell-only grid (DESIGN.md phase B/C): every open fill has its own
        breakeven-plus exit level; any uptick peels the deepest eligible
        slice. No buys ever happen in this mode - exposure only decreases.
        reserve_deepest: keep the single deepest fill as a combo counterweight
        for a later Wave Rider phase (never applies to the last fill).
        """
        eligible = list(fills)
        if reserve_deepest and len(fills) > 1:
            deepest = min(fills, key=lambda f: f["price"]) if self.is_long \
                else max(fills, key=lambda f: f["price"])
            eligible = [f for f in fills if f["id"] != deepest["id"]]

        margin = self.grid_margin_perc / 100.0
        hit = []
        for f in eligible:
            level = f["price"] * (1 + margin) if self.is_long else f["price"] * (1 - margin)
            if (current_rate >= level) if self.is_long else (current_rate <= level):
                hit.append(f)
        if not hit:
            return None

        # Deepest hit fill first = maximum de-risking per wave.
        target = min(hit, key=lambda f: f["price"]) if self.is_long \
            else max(hit, key=lambda f: f["price"])
        trade.set_custom_data("pending_skim", [target["id"]])
        trade.set_custom_data("pending_skim_recycle_rung", 0)
        if len(fills) == 1:
            return -trade.stake_amount, "grid_full_close"
        qty_to_sell = min(target["qty"], trade.amount)
        return -(qty_to_sell * current_rate), "grid_close"

    def _phase_d_decision(self, trade: Trade, fills: list, current_rate: float,
                          current_time: datetime):
        """
        Phase D capitulation (DESIGN.md section 3): mechanical, logged, no
        discretion. Rules in strict order:
          1. residual loss <= threshold  -> close (cost of a broken thesis)
          2. still a wave coin + regime OK + extension unused -> extend ONCE
          3. otherwise -> close
        """
        waves = self._deal_age_waves(trade, current_time)
        extensions = self._cd_int(trade, "phase_d_extensions", 0)
        deadline = self.decision_waves + self.decision_wait_waves * (1 + extensions)
        if waves < deadline:
            return None  # still deliberating; grid exits keep working

        cost = sum(f["size_usd"] for f in fills)
        value = sum(f["qty"] for f in fills) * current_rate
        loss_perc = 100.0 * (cost - value) / cost if self.is_long \
            else 100.0 * (value - cost) / cost
        score = self._pair_wave_score(trade.pair)

        if loss_perc <= self.phase_d_loss_threshold_perc:
            decision, reason = "close", (
                f"residual loss {loss_perc:.1f}% <= {self.phase_d_loss_threshold_perc}% threshold")
        elif (score is not None and score >= self.phase_d_min_wave_score
              and extensions < self.phase_d_max_extensions
              and not self._market_in_crash(current_time, trade.pair)):
            decision, reason = "extend", (
                f"wave score {score:.2f} >= {self.phase_d_min_wave_score}, regime OK")
        else:
            decision, reason = "close", (
                f"loss {loss_perc:.1f}%, score {score}, extensions {extensions} - thesis broken")

        self._log_phase_d({
            "time": current_time.isoformat(),
            "pair": trade.pair,
            "decision": decision,
            "reason": reason,
            "deal_age_waves": round(waves, 2),
            "wave_period_hours": self._wave_period_hours(trade.pair),
            "open_fills": len(fills),
            "cost_usd": round(cost, 2),
            "value_usd": round(value, 2),
            "loss_perc": round(loss_perc, 2),
            "wave_score": score,
            "extensions_used": extensions,
        })

        if decision == "extend":
            trade.set_custom_data("phase_d_extensions", extensions + 1)
            return None
        trade.set_custom_data("pending_skim", [f["id"] for f in fills])
        trade.set_custom_data("pending_skim_recycle_rung", 0)
        return -trade.stake_amount, "phase_d_close"

    def _log_phase_d(self, payload: dict) -> None:
        """Append to the decision log - the tuning dataset for Phase D rules."""
        log_path = Path(self.config["user_data_dir"]) / "logs" / "phase_d_decisions.jsonl"
        try:
            with log_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(payload) + "\n")
        except OSError:
            pass

    # ================= LEDGER BOOKKEEPING (actual fills only) =================

    def order_filled(self, pair: str, trade: Trade, order, current_time: datetime) -> None:
        fills = self._get_fills(trade)

        if order.ft_order_side == trade.entry_side:
            price = order.safe_price
            qty = order.safe_filled
            if not fills:
                # This is the base order: anchor the whole deal on its price.
                trade.set_custom_data("base_price", price)
                trade.set_custom_data("next_so_index", 1)
                if self.dynamic_ladder_enabled:
                    amp = self._pair_amplitude(trade.pair)
                    if amp:
                        clamp = lambda v: max(self.dynamic_min_perc,
                                              min(self.dynamic_max_perc, v))
                        trade.set_custom_data("deal_dev_perc",
                                              clamp(self.dynamic_spacing_mult * amp))
                        trade.set_custom_data("deal_tp_perc",
                                              clamp(self.dynamic_tp_mult * amp))
                        logger.info(
                            f"{trade.pair}: dynamic ladder set - spacing "
                            f"{clamp(self.dynamic_spacing_mult * amp):.2f}%, "
                            f"TP {clamp(self.dynamic_tp_mult * amp):.2f}% "
                            f"(amplitude {amp:.2f}%)")
                fill_id = "BO"
            else:
                recycle_rung = self._cd_int(trade, "pending_recycle", 0)
                if recycle_rung:
                    # A recycled refill: unique id (a rung can be recycled
                    # many times), taken off the refill queue, and the fresh
                    # rung pointer does NOT advance.
                    seq = self._cd_int(trade, "fill_seq", 0) + 1
                    trade.set_custom_data("fill_seq", seq)
                    fill_id = f"SO{recycle_rung}R{seq}"
                    refills = self._cd_list(trade, "refill_rungs")
                    if recycle_rung in refills:
                        refills.remove(recycle_rung)
                        trade.set_custom_data("refill_rungs", refills)
                    trade.set_custom_data("pending_recycle", 0)
                else:
                    so_index = self._cd_int(trade, "next_so_index", 1)
                    trade.set_custom_data("next_so_index", so_index + 1)
                    fill_id = f"SO{so_index}"
            fills.append({
                "id": fill_id,
                "price": price,
                "qty": qty,
                "size_usd": price * qty,
            })
            trade.set_custom_data("open_fills", fills)

        else:  # exit side: a skim (or a manual/forced exit) just filled
            pending = trade.get_custom_data("pending_skim", default=None)
            if pending:
                fills = [f for f in fills if f["id"] not in pending]
                # Partial skim + recycling enabled: the deepest closed rung
                # (armed in adjust_trade_position) joins the refill queue -
                # ONE reopened order for the 2-3 that just closed.
                recycle_rung = self._cd_int(trade, "pending_skim_recycle_rung", 0)
                if recycle_rung and fills:
                    refills = self._cd_list(trade, "refill_rungs")
                    refills.append(recycle_rung)
                    trade.set_custom_data("refill_rungs", refills)
            elif fills:
                # Exit we didn't initiate (e.g. force-exit from the UI):
                # best effort - drop the outer pair the spec would have chosen.
                fills = fills[1:-1] if len(fills) > 1 else []
            trade.set_custom_data("pending_skim", [])
            trade.set_custom_data("pending_skim_recycle_rung", 0)
            trade.set_custom_data("open_fills", fills)
