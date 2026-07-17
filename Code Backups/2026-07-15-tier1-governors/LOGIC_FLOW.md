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
    stint runs used (3 closed deals since joining the list)
ELSE allow. (Entry signal is always on — a flat coin always wants a deal.)
```

## Per open deal, every ~5s — `adjust_trade_position`

```
skip if an order is already pending, or the fill ledger is empty

1. DRAIN FAST-EXIT   draining AND loss ≤ 0.2%  → close everything ("drain_close")

2. CORRIDOR BRAKE    latched? OR drawdown-from-base > max(1.5 × coin amplitude, 12%)
                     OR exposure > 60% of per-coin cap
                     → latch (until deal closes) → SELL-ONLY GRID

3. CRASH FREEZE      BTC −5%/24h (with hysteresis) → SELL-ONLY GRID (all buys halted)

4. LIFECYCLE PHASE   by deal age in THIS COIN's wave periods:

   grace  (< 3 waves)   exit: full-position TP = blended avg of ALL fills + 2%
                         buys: fresh SOs only
   wr                    exit: COMBO SKIM — greedy min-TP combo of extreme fills
                              (≤ 3 fills, oldest ALWAYS included), TP = combo avg + 2%
                              partial skim → queue ONE recycle at deepest closed rung
                         buys: queued recycle rung first, then next fresh rung
                              every buy gated by: per-coin cap AND aggregate ceiling
   grid                  exit: SELL-ONLY — each fill at its own price + 0.5%,
                              deepest eligible first, single deepest fill reserved
                         buys: none
   decision (≥ 12 waves) exit: grid with reserve OFF, plus at the deadline:
                              loss ≤ 15%            → close (capitulation)
                              wave score ≥ 2 & regime OK & no extension used
                                                    → extend ONCE
                              otherwise             → close
                         every decision appended to phase_d_decisions.jsonl

   (grace-fail plans B/C order: config "grid,wr" — grid before wave rider)
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
drain a coin:    capitulated this stint | stint > 72h | earning < $0.05/day after 24h
retire when:     (3 runs done OR draining) AND flat  → slot refills from ranking
                 (24h cooldown before a retired coin may rejoin)
publish:         pairlist.json + state (join dates, draining, scores,
                 amplitudes, wave periods) — the strategy reads this state
```

## Invariants (never phase-dependent)

- Spot only, no leverage. No price stop-loss anywhere.
- Small fixed orders; ladder rungs pre-computed at BO, never ad-hoc.
- Per-coin cap checked before EVERY buy; aggregate 60% ceiling above it.
- Exits realize per-fill truth from the ledger; freqtrade's per-exit
  profit% is average-cost accounting and can look negative on a
  profitable slice (see grid_close notes in README).
