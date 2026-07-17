# Wave Rider — Design Document

Consolidated architecture agreed on 2026-07-14. This is the reference spec
for the lifecycle build and the backtesting phase. The original core-mechanic
spec lives in `../wave_rider_dca/REGENERATION_PROMPT.md`; this document
extends it — where they conflict, this one wins.

## Thesis

Every trader eventually gets stuck in a bad deal; getting out of bad deals is
the most important skill. Wave Rider deliberately starts "stuck" with a very
small base order, then uses selective sub-order combinations to reduce
exposure on every wave of price fluctuation. Volatility is the fuel: the
strategy sacrifices trend profits for account safety. The enemy is not
drawdown — it is dead ("zombie") capital.

## 1. Deal lifecycle (the core architecture)

A deal ages through phases. **Phases change exit behaviour only** — entry
sizing, ladder math, and capital caps are identical in every phase.

| phase | mechanism | buys allowed | exits |
|---|---|---|---|
| A — Trend grace | classic DCA | fresh SOs | full-position TP on blended average |
| B/C — Wave Rider | combo skims + recycling | fresh SOs + recycled refills | greedy min-TP combo of extremes |
| B/C — Sell-only grid | liquidation ladder | none | per-fill breakeven-plus levels, deepest first |
| D — Decision | capitulation | none | grid-style exits + mechanical close/extend |

- A deal that closes in the grace window was a trend dip — cheapest win.
  Pure Wave Rider = `grace_waves: 0`.
- **Phase order for B/C is configuration, not doctrine** (`phase_order`):
  `"wr,grid"`, `"grid,wr"`, or `"regime"` — decided mechanically per deal at
  grace failure: healthy market → Wave Rider first (waves likely — exploit
  them); regime brake active → grid first (continued fall likely — harvest
  the easy inventory, hold SO powder, deploy deep later).
- **Deepest-fill reserve**: the sell-only grid never sells the single deepest
  fill while older fills remain, so Wave Rider always inherits a combo
  counterweight.
- **Deferred-rung crash guard**: in grid-first plans the paused ladder rungs
  bulk-deploy when Wave Rider engages; that deployment is blocked while the
  regime brake is active — never buy maximum counterweight into a
  market-wide crash.

## 2. Wave-normalized timing — no clock constants

Regimes don't respect clocks; a coin's own rhythm defines "too long".

- The sidecar measures each coin's typical **wave period** (direction changes
  in the close series it already fetches) and publishes it in
  `pairlist_state.json`.
- All phase boundaries are in wave periods: `grace_waves` (default 3),
  `winddown_waves` (6, B→C), `decision_waves` (12, →D),
  `decision_wait_waves` (6, D deliberation). Clock fallback:
  `wave_period_fallback_hours` (4) when wave data is missing.

## 3. Capitulation (Phase D) — mechanical, logged, no discretion

- Entering Phase D: **no new orders**; grid-style exits keep peeling anything
  that becomes profitable (reserve off — everything sellable).
- At the deadline, rules evaluated in strict order:
  1. Residual unrealized loss ≤ `phase_d_loss_threshold_perc` (15% of that
     coin's committed capital) → **close**, free the slot; the small loss is
     the cost of a broken thesis.
  2. Coin's current wave score ≥ `phase_d_min_wave_score` AND regime brake
     inactive AND extensions used < `phase_d_max_extensions` (1) →
     **extend one** more deliberation window. Never more than one —
     extensions are where zombie capital regenerates.
  3. Otherwise → **close**.
- Every decision is appended to `user_data/logs/phase_d_decisions.jsonl`
  with its inputs — that log is the tuning dataset.
- Hedging: deferred to v3 (needs futures, funding costs, untestable in spot
  dry-run). Revisit only if the decision log shows frequent closes of
  positions that subsequently recovered.
- **Conscious spec amendment**: Phase D can realize losses. This is a
  time-boxed *thesis-invalidation* exit ("this coin stopped waving"), not a
  price stop-loss.

## 4. Capital invariants (all phases, non-negotiable)

- Small base order — cheap admission to the stuck state.
- Identical ladder sizing in every phase.
- Hard per-coin cap (1000 USDT) checked before **every** buy — fresh SO,
  recycled refill, or deferred rung.
- Max 10 concurrent coins; worst case = 10 × cap, known in advance.

## 5. Coin selection & rotation (implemented)

- **Score = wave amplitude** (avg 4h high-low swing % over one week),
  optionally × (1 − trendiness). Liquidity is a filter, never the score.
- Toggleable gates (all currently on): 24h volume floor; **median-daily
  volume floor** (the pump-and-dump gate — a spike inflates one day, not the
  median); choppiness filter (trendiness = |net move| ÷ path length; drops
  one-way movers — pumps AND crashes); spread < 0.1%; listing age ≥ 14 days.
- Rotation: `max_deal_restarts` runs per stint (per-stint counting — a
  returning coin gets a fresh allowance), 72h stint drain, 24h rejoin
  cooldown, retire-when-flat, slot refills from the ranking.
- **BTC regime brake**: pause new base orders portfolio-wide when BTC is
  down > 5%/24h. Existing deals keep managing. Fails open.

## 6. Exit mechanics (implemented)

- **Best-combo selection**: greedy minimum-TP combo of extreme fills, capped
  at `combo_max_orders` (3), oldest fill always included — worst inventory
  exits first; book quality improves with every skim.
- **Recycling**: a partial skim closes 2–3 fills and reopens exactly ONE at
  the deepest closed rung's pre-calculated price; recycled fills never
  advance the fresh-rung pointer; auto-disabled when draining.

## 7. Validation path

1. Backtest the **flag matrix** (phase order × grace window × recycling ×
   selector filters) — every design decision above is a config flag so this
   matrix is runnable.
2. Walk-forward across separated regimes (trend up, trend down, chop);
   reject configs that only win in one regime.
3. Score the selector separately from the strategy: wave-capture rate vs
   freeze rate per coin cohort.
4. Extended dry-run of the winner → small live capital → scale only after
   live matches paper.

## Live milestones (dry-run, 2026-07-14)

- Full rotation loop observed end-to-end: SXT completed 3 runs (+1.65%,
  +1.73%, +1.69% net), retired, SYN joined from the filtered ranking 30s
  later.
- 0.3%-threshold demo validated the skim machinery end-to-end (30 deals,
  all profitable, restart caps enforced).
