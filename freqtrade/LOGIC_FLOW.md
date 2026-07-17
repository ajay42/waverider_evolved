# Wave Rider — Logic Flow (simplified reference)

One page of pseudocode mirroring the deployed code, for checking the logic
without reading 1,100 lines. **Update this file whenever the flow changes**
— it is snapshotted into every code backup. Precedence order in each block
is the real order in code.

## New deal gate — `confirm_trade_entry` (fresh deals only, never SOs)

```
REJECT the new base order if any of:
    pair is DRAINING                          (sidecar rotation)
    pair capitulated this stint               (a phase_d_close since join)
    BTC regime crash (−5%/24h)                (regime brake)
    crash freeze active                       (hysteresis: −5% in, −2% + 6h dwell out)
    aggregate exposure > 60% of wallet        (portfolio ceiling)
    coin is RETIRED (hard block; survives list-refresh lag)
    a drain_close happened this stint (eviction ends the stint)
ELSE allow. (Entry signal is always on — a flat coin always wants a deal.)
```

## Per open deal, every ~5s — `adjust_trade_position`

```
skip if an order is already pending, or the fill ledger is empty

1. DRAIN FAST-EXIT   draining AND loss ≤ 1.0%  → close everything ("drain_close")

2. CORRIDOR BRAKE    latched? OR drawdown-from-base > max(1.5 × coin amplitude, 12%)
                     OR exposure > 60% of per-coin cap
                     → latch (until deal closes) → SELL-ONLY GRID

3. CRASH FREEZE      BTC −5%/24h (with hysteresis) → SELL-ONLY GRID (all buys halted)

4. LIFECYCLE SEQUENCE (config "grid,wr" — the stage-1 matrix winner).
   Ages are in THIS COIN's wave periods (~13-17h each on typical picks):

   1. GRACE     waves 0-3  (~day 0-2)
                exit: ONE target closes the whole position at
                      blended avg of ALL fills + 2%
                buys: fresh SOs ladder in normally
   2. GRID      waves 3-6  (~day 2-4)   "overstayed - start reducing"
                exit: SELL-ONLY, each fill at its own cost + 0.5%,
                      deepest eligible first; single deepest fill
                      reserved as the combo seed for stage 3
                buys: none
   3. WAVE-RIDE waves 6-12 (~day 4-8)   the classic mechanic
                exit: COMBO SKIM — greedy min-TP combo of extreme fills
                      (≤ 3, oldest ALWAYS included), TP = combo avg + 2%;
                      partial skim queues ONE recycle at deepest closed rung
                buys: recycle rung first, then remaining fresh rungs;
                      every buy gated by per-coin cap AND aggregate ceiling
   4. DECISION  wave 12+   (~day 8+)    last stop
                exit: grid with reserve OFF; at the wave-18 deadline:
                      loss ≤ 15%                         → close (capitulate)
                      wave score ≥ 2 & regime OK & unused → extend ONCE
                      otherwise                           → close
                      hard end by wave 24 (~2.5 weeks); every decision
                      logged to phase_d_decisions.jsonl

   Interrupts (any stage, paint the ribbon DARK RED): coin brake,
   crash freeze, drain — all sell-only, none is a price stop-loss.
```

## Fill ledger — `order_filled`

```
entry filled:  first fill anchors base_price; ladder = pure function of base price
               fresh SO advances the rung pointer; RECYCLED fill does NOT
exit filled:   remove exactly the fills named in pending_skim
               partial skim + recycling on → push deepest closed rung to refill queue
               (ledger records ACTUAL fill prices — it always matches the wallet)
```

## Sidecar — `pairlist_updater.py`, every 15 min

```
score universe:  wave amplitude (avg 4h high-low % over a week) × (1 − trendiness)
filters:         24h volume floor, MEDIAN-daily volume floor (P&D gate),
                 spread < 0.1%, listing age ≥ 14d, choppiness (trendiness ≤ 0.4)
drain a coin:    capitulated this stint | drain-evicted this stint |
                 wave score < 2.0 quality floor (rotation is QUALITY-driven,
                 not counter-driven - run limit removed 2026-07-15) |
                 stint > 72h | earning < $0.05/day after 24h
retire when:     draining AND flat  → slot refills from ranking
                 (24h cooldown; retired coins hard-blocked at the entry gate)
publish:         pairlist.json + state (join dates, draining, scores,
                 amplitudes, wave periods) — the strategy reads this state
```

## Invariants (never phase-dependent)

- Spot only, no leverage. No price stop-loss anywhere.
- Small fixed orders; ladder rungs pre-computed at BO, never ad-hoc.
- Per-coin cap checked before EVERY buy; aggregate 60% ceiling above it
  on FRESH deployment. Parked (never-buy-again) capital is exempt up to
  20% of wallet (reserve underwrites the workout bags) - exemption
  inactive during a crash freeze and for 6h after it releases. Hard
  floor no code path can touch: 20% of wallet. Joiners must clear the
  same 2.0 quality floor as members - empty slot beats mediocre coin.
- Exits realize per-fill truth from the ledger; freqtrade's per-exit
  profit% is average-cost accounting and can look negative on a
  profitable slice (see grid_close notes in README).
- Chart language: yellow = next buy rung, cyan = whole-position average,
  green = the ARMED exit trigger for the current stage/mode, magenta =
  every order that armed exit will close (all fills in grace, the 1-3
  combo in wave-ride, each eligible fill in grid/lockdown), ribbon =
  stage colors with dark red for governor overrides.
