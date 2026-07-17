# Wave Rider — Capital Safety Roadmap

Recommendations agreed on 2026-07-15, to be implemented behind config flags and
backtested before any live capital. **Status update (2026-07-15, later): P0-1
(corridor brake), P0-2 (crash freeze + hysteresis), and P1-1 (aggregate
governor) are IMPLEMENTED in `WaveRiderDCA.py` per this spec — flags default
off in code, enabled in `config.json`. P1-2 (%-wallet sizing) remains spec-only.
Tail-window backtests (section "Backtest plan") are the next gate.** This file
extends `DESIGN.md`; where they conflict, DESIGN.md's core mechanic wins and
this file only adds safety governors on top.

Priority for this phase: **capital safety first**, returns second. Several of
these trade skim upside for tail protection — that is the intended direction.

---

## Why (findings that motivate the list)

Grounded in the deployed `WaveRiderDCA.py` + `config.json` and the exposure
model in `../scratchpad/ladder_model.py` (per-coin cap $1000 = 10% of a $10k
wallet, base orders $10, ladder covers 30% drawdown).

1. **Good baseline: no leverage.** `trading_mode: spot`, no margin, `can_short:
   false`. Max loss is bounded by capital deployed — no liquidation, no margin
   call. Everything below is drawdown *within* deployed capital, not ruin.

2. **Gap — caps sum to ~100% of the account.** `max_open_trades: 10` ×
   `max_exposure_per_coin_usd: 1000` = $10,000 ≈ the $9,900 tradable balance.
   There is **no account-level reserve and no aggregate governor**. In a
   correlated dump all 10 slots fill toward cap at once → ~100% deployment with
   zero dry powder. The per-coin cap does nothing at the portfolio level.

3. **Gap — the regime brake is too narrow.** `confirm_trade_entry` blocks new
   *base* orders on a BTC −5%/24h crash, but `adjust_trade_position` keeps
   firing SOs and recycles on already-open deals. Since a crash finds you
   already holding 10 deals, deployment *grows* through the crash.

4. **Reframe — phase-D's −15% is NOT a stop.** Because DCA drags the average
   entry to −18%…−21%, the *position* is not 15% underwater until *price* is
   **−31% to −34%** — past the ladder floor, in the frozen zone, with 89–100%
   of the cap already deployed. A loss-% threshold can never be an early risk
   control on a DCA ladder (even −8% only pulls it to ~−24%). Phase-D's real
   protective value is its **wave-age time-box**, not the loss number. Do not
   tune the loss % for safety.

5. **`volume_scale` back-loads the tail.** The geometric multiplier is the skim
   engine (big deep orders drag combos out), and order count grows only
   *logarithmically* with the cap (~25 orders at $1k, ~48 at $10k — not
   hundreds). But it concentrates capital in the deepest rungs:

   | `v` | SOs to cap | deep SO $ | exp @ −10% | exp @ −20% | exp @ −30% | % of cap in −20→−30% band |
   |---|---|---|---|---|---|---|
   | 1.15 | 19 | 124 | 98 | 300 | 892 | **66%** |
   | 1.10 | 25 | 98 | 124 | 369 | 993 | 63% |
   | 1.05 | 36 | 55 | 169 | 455 | 968 | 53% |
   | 1.02 | 55 | 29 | 224 | 530 | 996 | 47% |

   High `v` is capital-*efficient* AND safe **only if an exit fires before the
   deep band** (at −20% it has deployed just $300 vs the flat ladder's $530).
   Left to run, it dumps two-thirds of the cap into −20→−30%.

6. **The unprotected corridor is −10%→−30%.** The freeze (if it fires) caps you
   at −10%; phase-D wakes at −31%. Between them — where the convex ladders spend
   the bulk of their capital — there is no per-coin brake at all.

**Conclusion:** the *freeze and a per-coin brake* are the load-bearing capital
safety levers. Phase-D is a deep backstop, not a control. The single highest-
value change is a per-coin brake owning the −10%→−30% corridor.

---

## Recommendations (priority order)

### P0-1 — Per-coin corridor brake  ★ highest leverage

Fill the −10%→−30% gap with a brake that listens to *this coin*, independent of
the BTC regime signal (which won't fire if an alt bleeds while BTC is flat).

**Trigger — wave-normalized** (so it does not strangle high-amplitude coins,
which are exactly the ones we select for). Fires when ANY of:
- (a) coin drawdown from base `>` `coin_brake_wave_mult` × wave amplitude
  (thesis broken: fell well past a normal wave for this coin);
- (b) coin drawdown from base `>` `coin_brake_floor_perc` (absolute backstop for
  tiny-amplitude coins);
- (c) deployed exposure `>` `coin_brake_exposure_frac` × cap (catches
  recycling buildup that price-drawdown alone misses).

A 10%-wave coin brakes at ~−15%; a 20%-wave coin at ~−30%. "Fell further than
its own waves explain," not a fixed price.

**Action.** Latch the deal into sell-only: freeze all buys (BO/SO/recycle),
route to `_grid_exit_check(..., reserve_deepest=False)` so it drains. Reuses
existing phase-C machinery.

**Release.** Latch until the deal fully closes — no unbrake threshold, no
re-arming into the fall. A coin that broke its wave thesis winds down; if it
rejoins the pairlist later it starts fresh. Simpler and strictly safer than
hysteresis.

**Impact (from the model).** Brake at 1.5× a 10% wave (≈ −15%) caps each ladder
at **$178–363 instead of $892–996** — a 60–80% cut. Convex ladders benefit most
(`v=1.15`: $892 → $178, −80%), which **dissolves the density↔`v`↔safety
tension**: the brake owns the tail, so `v` is a skim-tuning choice again.
Portfolio: 10 coins braked ≈ **$2,200 (22%) vs ~$9,900 (100%)** in a correlated
crash.

**Config knobs** (`wave_rider` section):
```
coin_brake_enabled: true          # default false in code
coin_brake_wave_mult: 1.5         # ×amplitude → thesis-break level
coin_brake_floor_perc: 12.0       # absolute min drawdown before (a) fires
coin_brake_exposure_frac: 0.6     # freeze at 60% of per-coin cap
```

**Integration** (mirrors `drain_fast_exit`, minimal surface):
- `bot_start`: add the four keys to the override loop.
- new `_coin_braked(trade, current_rate, fills)`: coin drawdown from
  `base_price`; amplitude from `_wave_stats_cache` / sidecar `scores`; the three
  conditions; latch via `set_custom_data("coin_braked", True)`.
- `adjust_trade_position`: check right after the `drain_fast_exit` block — if
  braked, `return self._grid_exit_check(trade, fills, current_rate,
  reserve_deepest=False)` and never reach `_safety_order_check`. Overrides phase.

**Cost / dial.** False positives: a coin that dips past the threshold then
recovers is wound down when it would have skimmed. `coin_brake_wave_mult` is the
dial (higher = fewer false brakes, deeper tail). Sweep it in the backtest.

---

### P0-2 — Crash freeze + force sell-only grid on OPEN deals

Extend the existing regime brake so a BTC crash freezes *all* buys on open deals
(not just new base orders) and flips them to sell-only grid. Stops deployment
growing at the point of maximum danger; preserves dry powder to open fresh deals
at post-crash prices.

- When `_market_in_crash()` is true: gate SO + recycle paths in
  `_safety_order_check` (currently only BOs are gated in `confirm_trade_entry`),
  and force every open deal to `_grid_exit_check`.
- **Hysteresis required** — the −5%/24h trigger is coarse and will flap. Freeze
  at `regime_brake_btc_drop_perc`, unfreeze only at a shallower level
  (`regime_unfreeze_btc_drop_perc`, e.g. −2%) AND a minimum dwell
  (`regime_min_freeze_hours`, e.g. 4–6h).
- **Re-entry rule** — define when buys resume (tie to the unfreeze condition).

Note: the grid at breakeven+ only *harvests bounces*; in a falling market its
exits sit above price and don't fire. **The freeze is the protection; the grid
is opportunistic.** Do not expect the grid to cut losses mid-crash.

**Config knobs:**
```
crash_freeze_enabled: true
regime_unfreeze_btc_drop_perc: 2.0
regime_min_freeze_hours: 6.0
```

**Relationship to P0-1:** complementary. The per-coin brake is cause-agnostic
(fires on any coin breakdown); the crash freeze is fast and BTC-aware (catches
the whole portfolio at once). Ship both. The crash freeze should kill the
**deepest/biggest pending rungs first** (largest exposure, most likely catching
a knife).

---

### P1-1 — Aggregate exposure governor

Belt-and-suspenders for the cause-agnostic case the BTC freeze misses (slow
grind, alt-sector bleed). Halt new SOs/BOs when total deployed across all trades
`>` `max_aggregate_exposure_pct` × balance.

- new helper summing open exposure across `Trade.get_trades_proxy(is_open=True)`;
  gate in both `confirm_trade_entry` and `_safety_order_check`.
- `max_aggregate_exposure_pct: 60` → hard 60% deployment ceiling, always a cash
  reserve by construction.

Alternative / complement: simply make the sum of per-coin caps `<` balance —
drop `max_exposure_per_coin_usd` to ~$600 (→ $6k, 60%) or `max_open_trades` to
6–7. The governor is more precise; the cap reduction is zero-code.

**Config knob:**
```
max_aggregate_exposure_pct: 60    # 0 or negative = disabled
```

---

### P1-2 — Cap as % of wallet, fixed order size, derived density

Make the strategy scale with the account **without** floating order sizes
(keeps fixed-$ legibility and exchange-min safety). Cap becomes a % of wallet;
spacing is derived so density rises with the cap; `volume_scale` stays (it is
the skim engine and, per finding 5, *lowers* loss at moderate drawdowns).

```
C        = max_exposure_per_coin_pct × wallet        # dollar cap, scales
N        = min(orders_to_reach(C, order_size, v), max_orders)
spacing  = ladder_depth_pct / N                      # narrower gaps as N grows
```

- **Wallet basis = free/available balance**, not total — as capital locks up in
  a crash, new SO sizes shrink automatically (emergent slowdown).
- **`max_orders` ceiling** is the operational guard. Because order count grows
  only logarithmically with `v>1`, the count stays ~25–48 across realistic
  wallets — but the ceiling matters on large wallets, and once
  `C/order_size > max_orders` you must let order size grow after all (a hybrid).
  Within the likely $2k–$20k band the pure fixed-size form is fine.
- Floor must clear Binance min-notional (~$5–10); on small wallets the floor
  dominates (= current fixed sizing).

**Config knobs:**
```
sizing_mode: "pct_wallet"         # "fixed" keeps today's behaviour
max_exposure_per_coin_pct: 10.0
ladder_depth_pct: 30.0
max_orders: 40
wallet_basis: "free"              # "free" | "total"
```

**`volume_scale` selection** (couples to P1-2): under a fixed cap, deep-order
magnitude and density trade off inversely via `v`. With P0-1's brake owning the
tail, **`v=1.10` is well-matched**. Without the brake, prefer **`v=1.05`**
(flatter deployment, 53% vs 63% in the deep band, more forgiving of late exits).

---

## Reframes / standing principles

- **Phase-D −15% is capitulation, not a stop.** It fires only when fully
  deployed and deep. For earlier bite, tune the *wave-age deadline*
  (`decision_waves`), never the loss %.
- **Freeze + per-coin brake are the load-bearing levers.** The regime freeze
  owns the shallow zone, the per-coin brake owns the −10%→−30% corridor,
  phase-D is the deep backstop. Three layers, different jobs.
- **Ladder shape and the brake are one system.** Choose `v` against how
  reliably the brake/freeze cuts before the deep band, not in isolation.

---

## Rejected / deferred (do not revisit without new reason)

- **Grace TP from BO price instead of blended average** — DROPPED (2026-07-15).
  Makes grace exits *later* (BO×1.02 > avg×1.02 for a long), holding longer and
  recycling capital slower — a returns tweak that cuts against the capital-
  safety priority. Bounded by `grace_waves` and small in practice, but not worth
  it now. Reconsider only if the goal shifts to profit-per-deal.
- **BO/SO order *sizing* as % of wallet** — SUPERSEDED by P1-2 (cap-as-% +
  fixed size + derived density), which keeps fixed-$ legibility. The floating-
  size version added drift/recompute complexity for no extra safety.

---

## Backtest plan (before any live capital)

**Prove the tail, not the body.** All validation so far is rallies/normal
swings; the real spec is worst-case *portfolio* drawdown.

1. **Regime windows** (use `scripts/find_regime_windows.py`): May 2021 crash,
   Nov 2021 → mid-2022 bear, and the May/Nov 2022 LUNA/FTX weeks — correlated
   crashes with all 10 slots stuck at once.
2. **Primary metric:** worst-case aggregate deployment and max portfolio
   drawdown (not win rate). Secondary: skim P&L given up vs the unbraked run.
3. **Flag sweep:**
   - `coin_brake_wave_mult ∈ {1.5, 2.0, 2.5}` (false-brake rate vs tail depth)
   - `coin_brake_enabled`, `crash_freeze_enabled`, `max_aggregate_exposure_pct`
     on/off — isolate each governor's contribution
   - `volume_scale ∈ {1.05, 1.10}` × brake on/off (confirm the brake makes high
     `v` safe)
4. **Acceptance:** with P0-1 + P0-2 on, worst-case correlated deployment stays
   ≤ ~`max_aggregate_exposure_pct`, and no single window realizes a portfolio
   drawdown beyond the agreed tolerance, before sizing up from demo.

---

## Implementation order

1. P0-1 per-coin brake (biggest single win; self-contained).
2. P0-2 crash freeze + grid on open deals (reuses `_market_in_crash`,
   `_grid_exit_check`).
3. P1-1 aggregate governor (thin, cause-agnostic backstop).
4. P1-2 %-wallet sizing (larger change; do after the governors so backtests
   compare like-for-like).

All flags default **off in code, on in `config.json`**, so the flag matrix
backtests cleanly against today's behaviour.
