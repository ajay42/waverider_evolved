# Wave Rider — Sequencer Refactor (target architecture)

Refactor target agreed 2026-07-15. **Not implemented** — this is the destination
shape for `WaveRiderDCA.py`. The goal is to make *logic sequencing* the readable
centre of the strategy and push everything else to the edges, so the accreted
mechanisms (lifecycle phases, recycling, safety governors) stop tangling into
one 100-line decision method.

Companion docs: `DESIGN.md` (behaviour spec), `CAPITAL_SAFETY.md` (the governors
that will land as table rows here). Where structure and behaviour interact, this
file governs *structure only* — it must not change behaviour on the first pass.

---

## Principle: separate policy / mechanism / data

Today `adjust_trade_position` interleaves three concerns. Split them:

| Layer | Job | Rule |
|---|---|---|
| **Policy** — the sequencer | decide *which* action a position takes this tick | one ordered table; this is the main thing you read |
| **Mechanism** — handlers | *do* one action to a position | uniform signature, return an order or nothing |
| **Data** — sidecars | *compute* state (ladder math, waves, combos, exposure, filters) | pure functions, no order placement, no trade writes |

The sidecars are **already mostly pure** in the current code — the real work is
extracting the dispatch into an explicit table and giving handlers one signature.

---

## The sequencer (policy)

`adjust_trade_position` shrinks to: build context once, run guards, run the
ordered action chain.

```python
def adjust_trade_position(self, trade, current_time, current_rate, ...):
    ctx = self._build_context(trade, current_rate, current_time, min_stake, max_stake)
    if any(guard(ctx) for guard in self.GUARDS):
        return None
    for applies, handle in self.ACTIONS:
        if applies(ctx):
            result = handle(ctx)
            if result is not None:      # handler may decline (e.g. cap didn't fit) → next row
                return result
    return None
```

- **GUARDS** — cheap short-circuits that mean "do nothing this tick":
  orders still pending, ledger not yet initialised.
- **ACTIONS** — ordered `(condition, handler)`. First condition that matches
  *and* whose handler returns an order wins. A handler that returns `None`
  falls through to the next row (this is how cap-gated buys decline cleanly).

### `self.ACTIONS` — the whole position logic, top to bottom

```
   condition (applies)                         handler
1  draining & at/near breakeven                h_drain_close
2  winddown mode (braked | draining)           h_grid_sell        (reserve_deepest=False)
3  decision mode                               h_grid_sell        (reserve off) then …
4  decision mode & past deadline               h_capitulate
5  grace mode & blended-avg TP hit             h_grace_close
6  wave mode & combo TP hit                    h_skim             (arms recycle)
7  buys allowed & recycle rung hit             h_place_recycle    (cap-gated → may decline)
8  buys allowed & next SO rung hit             h_place_so         (cap-gated → may decline)
```

`buys allowed` = mode in {grace, wave} AND not braked AND not draining AND not
(regime crash blocking new buys). Encoding the crash/brake gate *inside* the buy
conditions removes the old free-standing "regime blocks buys" branch — the buy
rows simply don't apply.

Reordering priority = reordering this list. Adding a mechanism = adding a row.
The lifecycle "phases" are now emergent from row eligibility + `ctx.mode`, not a
separate computed state machine.

---

## The context object (data, gathered once)

`_build_context` reads all state a tick needs, so handlers/conditions never
recompute or re-read:

```
ctx.trade, ctx.rate, ctx.time, ctx.min_stake, ctx.max_stake
ctx.fills            # list[dict]  (from _get_fills)
ctx.base_price, ctx.next_so_index, ctx.refill_rungs
ctx.exposure, ctx.cap
ctx.mode             # "grace" | "wave" | "winddown" | "decision"  (see below)
ctx.age_waves, ctx.wave_period_h, ctx.wave_score
ctx.braked, ctx.draining, ctx.crash   # bools from sidecar state readers
```

**Effective mode** replaces `_deal_phase` / `_phase_plan`, by priority:

```
decision   if age_waves >= decision_waves
winddown   elif braked or draining
grace      elif age_waves <  grace_waves
wave       else
```

Note grid-as-a-lifecycle-phase is gone: grid selling is now *only* a wind-down
behaviour (braked / draining / decision). This is the linearisation from
`CAPITAL_SAFETY.md` — no `phase_order`, no plan pinning, no deferred-rung guard.

---

## Handlers (mechanism)

Uniform signature `def h_x(self, ctx) -> Optional[tuple[float, str]]` — return
`(stake, tag)` to act (positive = buy, negative = sell), or `None` to decline.
Each is a thin wrapper over sidecar math; **no state reads beyond `ctx`**.

| handler | does | returns None when |
|---|---|---|
| `h_drain_close` | close whole position, tag `drain_close` | — |
| `h_grid_sell` | peel deepest eligible fill at breakeven+; full-close if last | no fill above its level |
| `h_capitulate` | mechanical close (wave-age deadline); logs decision | before deadline |
| `h_grace_close` | full-close on blended-avg TP, tag `grace_full_close` | — |
| `h_skim` | close chosen combo; arm recycle rung if partial | — |
| `h_place_recycle` | place shallowest queued refill, cap-gated | cap doesn't fit |
| `h_place_so` | place next fresh rung, cap-gated | cap doesn't fit |

Conditions are matching predicates (`c_skim_ready`, `c_so_rung_hit`, …) — each a
few lines reading only `ctx` + sidecars. Keeping the cap check *inside*
`h_place_*` (decline → fall through) is deliberate: the condition stays simple
("rung price reached"), the handler owns the sizing arithmetic.

---

## Sidecars (data — pure, unit-testable)

Direct map from current functions. These move to a `wave_rider_lib.py` module
(importable from `user_data/strategies/`) or a clearly-sectioned block of
`@staticmethod`s — either way, **no Freqtrade objects mutated, no orders**.

| sidecar group | current functions |
|---|---|
| ladder math | `_stepped_deviation_percent`, `_so_trigger_price`, `_so_size_usd` |
| combo selection | `_select_skim_combo` |
| wave stats | `_update_wave_stats`, `_wave_period_hours`, `_pair_wave_score`, `_deal_age_waves` |
| exposure/ledger read | `_exposure_usd`, `_fill_rung_index`, `_cd_int/_cd_float/_cd_list`, `_get_fills` |
| external state readers | `_pairlist_state`, `_pair_joined_at`, `_is_draining`, `_market_in_crash` |

Pure functions mean the whole decision layer can be unit-tested with fabricated
`ctx` objects — no bot, no exchange, no backtest harness.

---

## What stays OUTSIDE the sequencer

These are separate concerns and must not be folded in:

- **`order_filled`** — the one place that *writes* the ledger (fills, recycle
  bookkeeping, `next_so_index`). Mechanism for state-keeping, not policy. Keep
  isolated and unchanged.
- **`confirm_trade_entry`** — the new-deal gate (restart cap, drain, regime,
  phase-D-close, rejoin). Its own small ordered guard list, same pattern, but a
  distinct decision point (open vs adjust).
- **`custom_stake_amount`** — base-order sizing.
- **`populate_indicators` / `populate_entry_trend` / `populate_exit_trend`** —
  framework plumbing and FreqUI chart lines. The indicator code reads the same
  sidecars but stays in its callback.
- **`bot_start`** — config overrides.

---

## Migration (behaviour-identical first)

**Phase 1 — port, don't change.** Restructure to sequencer + handlers + sidecars
producing byte-identical decisions to today, *including* current lifecycle
behaviour temporarily (extra rows/conditions for the existing `phase_order` grid
branch). Validate: run the same backtest window before/after and diff the trade
list — must match. This de-risks the refactor from the feature changes.

**Phase 2 — simplify via table edits.** Only after Phase 1 is green:
- unify the wind-down triggers → rows 1–4 already share `h_grid_sell`.
- linearise lifecycle → delete the `phase_order`/plan rows and conditions.
- reduce phase-D → `h_capitulate` becomes wave-age-only (drop extend/wave-score).
- add per-coin brake (`CAPITAL_SAFETY.md` P0-1) → set `ctx.braked`; **row 2
  already handles it**. No new dispatch code.

Each Phase-2 change is a localized edit to the table or one condition, re-tested
independently — which is the entire point of doing the structure first.

---

## Cautions

- **Keep it a plain list of methods.** `GUARDS` / `ACTIONS` are literal lists of
  `(predicate, method)` on the class. No registry, no config-driven rule
  loading, no dynamic handler discovery — that relocates complexity, doesn't
  remove it. Resist abstracting the abstraction.
- **Hot path.** This runs every tick per open trade. Build `ctx` cheaply and let
  the guard short-circuit before any heavier computation. Profile if needed.
- **Don't merge `order_filled` in.** Reads (sequencer) and writes (order_filled)
  stay on separate sides.
- **One behaviour change at a time** in Phase 2, each with its own before/after
  backtest diff.

---

## Target module layout

```
user_data/strategies/
  WaveRiderDCA.py        # IStrategy: callbacks + GUARDS/ACTIONS table + handlers + _build_context
  wave_rider_lib.py      # pure sidecars (ladder, combos, waves, exposure, state readers) — no Freqtrade imports where avoidable
```

Handlers stay on the strategy class (they read `ctx`, may set trade custom data
via the ledger writer). Sidecars are pure and live in `wave_rider_lib.py` so they
unit-test standalone. `order_filled` and the `populate_*` callbacks remain on the
strategy class, unchanged in responsibility.
