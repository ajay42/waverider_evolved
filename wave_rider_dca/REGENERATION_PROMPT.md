# Prompt: Build the "Wave Rider DCA" strategy in Python

Copy everything below this line into a fresh session to regenerate the implementation.

---

Build a Python reference implementation of a DCA (dollar-cost-averaging) crypto trading strategy called **Wave Rider DCA**. It is a port of a TradingView Pine Script strategy, with added risk controls. It must be pure Python (standard library only, no external packages), structured so a beginner can read it progressively, file by file. This is a *reference implementation / simulator* — no exchange connectivity; a later Freqtrade port will reuse its logic.

## Strategy concept

A base order (BO) opens a position immediately whenever the bot is flat — there is **no entry signal**; the strategy always wants to be in a deal. As price moves against the position, pre-calculated safety orders (SOs) of growing size fill one at a time, averaging the entry. Profit is taken by **skim-closing**: whenever price recovers past the take-profit level of the two *outermost* open orders (oldest-filled and newest-filled), close **only those two**, leaving the middle of the ladder open. The next-outermost pair then becomes the new first/last for the next skim. This repeatedly harvests profit from price waves while core exposure rides the larger move — hence "wave rider". This selective first+last close is the defining mechanic; do NOT replace it with a close-everything-at-average TP.

## File structure (build in this order)

```
wave_rider_dca/
  __init__.py     (empty)
  config.py       all tunable parameters, heavily commented
  ladder.py       pure functions: SO price/size math
  deal.py         state machine for one coin's deal lifecycle
  portfolio.py    runs up to N independent deals
  simulate.py     runnable synthetic-price demo
```

## config.py

A `StrategyConfig` dataclass with these fields and defaults, each with a plain-language comment. Include an `is_long` property (`strategy_type == "long"`).

| field | default | meaning |
|---|---|---|
| `strategy_type` | `"long"` | "long" or "short" (short is the full mirror image) |
| `take_profit_perc` | `2.0` | % past the outer-pair average that triggers a skim-close |
| `base_order_size_usd` | `10.0` | USD size of the deal-opening order |
| `safety_order_size_usd` | `10.0` | USD size of SO #1 |
| `max_safety_orders` | `15` | hard ceiling on ladder length |
| `safety_order_price_deviation_perc` | `2.0` | % move from BO price that triggers SO #1 |
| `safety_order_volume_scale` | `1.1` | each SO is this multiple of the previous SO's USD size |
| `safety_order_price_step_scale` | `1.0` | multiplier on the % gap between successive SO triggers |
| `max_exposure_per_coin_usd` | `1000.0` | hard cap on total USD committed per coin (BO + open SOs) |
| `max_deal_restarts` | `3` | lifetime number of full deals allowed per coin |
| `max_coins` | `10` | max concurrent coins in the portfolio |

## ladder.py — pure, deterministic functions

- `stepped_deviation_percent(so_index, deviation_perc, step_scale)`: cumulative % distance of SO `so_index` (1-based) from the BO price. Formula: `sum over step=1..so_index of deviation_perc * step_scale**(step-1)`. Returns 0.0 for so_index <= 0.
- `so_trigger_price(so_index, base_price, deviation_perc, step_scale, is_long)`: long → `base_price * (1 - dev/100)`, short → `base_price * (1 + dev/100)`.
- `so_size_usd(so_index, safety_order_size_usd, volume_scale)`: `safety_order_size_usd * volume_scale**(so_index - 1)` (geometric / martingale-style growth).
- `LadderRung` dataclass: `index` (1-based), `trigger_price`, `size_usd`, `qty` (= size_usd / trigger_price).
- `build_ladder(config, base_price) -> list[LadderRung]`: computes all `max_safety_orders` rungs. Called **once** when a BO fills; the ladder is **never mutated afterward** — every SO fires only at these pre-calculated points, never at ad-hoc prices.

## deal.py — the state machine (the core file)

A `Fill` dataclass: `id`, `kind` ("BO"/"SO"), `ladder_index` (0 for BO), `price`, `qty`, `size_usd`.

A `Deal` class with states `FLAT` / `ACTIVE`, holding: `coin`, `config`, `restart_count`, `base_price`, `ladder`, `next_so_index` (1-based pointer to the next unfilled rung), `open_fills` (ordered list, oldest first), `exposure_usd`, and a fill-id sequence.

Rules — implement exactly:

1. **Opening**: `can_start_new_deal()` = state is FLAT **and** `restart_count < max_deal_restarts`. `start_base_order(price)` fills the BO at the given price, sets exposure to the BO size, builds the ladder from that price, resets `next_so_index` to 1.
2. **Safety orders** (`try_fill_next_safety_order(current_price)`): only the single next rung is ever checked (strictly sequential, one SO max per tick, never skip ahead). Trigger: long → `current_price <= rung.trigger_price`; short → mirrored. Before filling, check the cap: if `rung.size_usd > max_exposure_per_coin_usd - exposure_usd`, do **not** fill, do **not** advance the pointer, do **not** resize — the rung simply waits, and may fire on a later tick if a skim-close frees capacity while price is still at/through it. On fill, record the fill **at the rung's trigger price** (limit-at-rung semantics, a confirmed deliberate deviation from the Pine original's market fills).
3. **Skim-close** (`find_skim_close(current_price)`): take the outer pair = `[open_fills[0], open_fills[-1]]` (or just the one fill if only one is open). Compute their **quantity-weighted** average price. TP price = `avg * (1 + tp/100)` for long, `avg * (1 - tp/100)` for short. Trigger: long → `current_price >= tp_price`; short → mirrored. `apply_skim_close` closes **only those fills** at the current price, realizes PnL, and subtracts their `size_usd` from exposure. **Non-renewal**: freed capital only reduces exposure; nothing is automatically re-opened, and there is **no stop-loss anywhere** — a deal frozen at the cap simply holds and waits to skim out profitably.
4. **Full close**: when `open_fills` empties, state → FLAT, `restart_count += 1`, ladder/base price cleared. After `max_deal_restarts` full deals, the coin never opens again (no automatic reset; lifetime counter).
5. **Tick order** (`step(current_price) -> list of event dicts`): (a) skim-close check first (may free cap headroom), (b) then SO check, (c) then — if flat and eligible — open a new BO **on the same tick** (no cooldown; confirmed deliberate). Emit event dicts: `BASE_ORDER_OPENED`, `SAFETY_ORDER_FILLED` (include ladder_index, price, size_usd, running exposure), `SKIM_CLOSE` (include closed fill ids, close price, realized PnL, whether the deal fully closed, restart_count).

## portfolio.py

`Portfolio(config, coins)`: raises `ValueError` if `len(coins) > max_coins`. Each coin gets its own fully independent `Deal` (own cap, own ladder, own restart counter — nothing shared). `step(prices: dict)` advances every coin present in the dict and returns all events. Helpers: `total_exposure_usd()`, `max_possible_exposure_usd()` (= max_coins × cap), `snapshot()` (one status row per coin).

## simulate.py

A runnable demo (`python simulate.py`), **not** a real backtest (no fees/slippage/historical data — say so in the docstring). Build a synthetic price series from hand-picked waypoints with linear interpolation plus small seeded random noise. The path must include: a dip deep enough to fill many SOs, a recovery that produces a chain of skim-closes ending in a full deal close, and enough cycles to hit the 3-deal restart limit. Pretty-print every event with tick, price, ids, sizes, PnL; end with a portfolio snapshot and total-vs-ceiling exposure line.

## Verification (run these before declaring done)

1. Run `simulate.py`: confirm BO opens at tick 0, SOs fill strictly in ladder order, skim-closes consume pairs outside-in ending in "deal fully closed", a new deal restarts, and after the 3rd full close **no** new BO opens (final snapshot: FLAT, restart_count 3, exposure 0).
2. Cap test: a steady one-way price decline (e.g. −0.5%/tick, no recovery) with `max_safety_orders=30`. Confirm SO fills stop when the next rung's size exceeds remaining capacity (exposure freezes below 1000), the pointer does not advance, and no forced exit ever occurs no matter how far price falls.

## Context for future work (do not implement now)

- An "order recycling" variant (re-opening a just-closed order to improve averaging) was considered and deferred; the cap check is per-new-SO so a recycled order would pass through the same gate.
- Next phase is a Freqtrade port; the limit-at-rung fill semantics map naturally to resting limit orders there.
- Webhook `bot_id` fields from the original Pine (3Commas integration) are intentionally dropped.
