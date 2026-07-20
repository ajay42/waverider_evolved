# WaveRider — Key Test Results & Expected Behaviour

One-page summary of every major validation and what behaviour to expect from
the code because of it. Full detail: `Analysis And Reports/` (dated reports).

## Key test results

- **Stage-1 matrix (30 runs, 3 regimes × cohorts × variants):**
  - lifecycle "grid-first" ordering = most consistent winner → is the live default
  - wave-scored cohort is the bear/chop edge; recycling needs the lifecycle
- **Selector predictive power (26 as-of dates, zero lookahead):**
  - decile-monotonic: top-scored coins produced 6.2 → 37.0 skimmable waves/week
  - median Spearman rank correlation **0.806** → selection is a real edge
- **Tail/crash battery (20 runs, real 2021/2022 crash windows):**
  - governors cut peak deployment **17–37% → ~6–7%** of wallet
  - worst window loss −3.33% governed vs −9.85% ungoverned; zero capitulations
    with the full stack
- **Win-probability model (16,259 backtest trades, walk-forward):**
  - win rate ~100% until price drawdown >10%; **17%** beyond 25% drawdown
  - win rate ~100% until ~12 waves of age; **14%** beyond 18 waves
  - → justified the 5-day age cap; losses concentrate exactly where designed
    (capitulations/forced exits)
- **Synthetic beyond-history crashes (12 runs, 6 engineered scenarios):**
  - capital traps ONLY when a crash has no waves AND no recovery
  - that trap scenario: **5-day cap is the only exit → trap closed** (~0% loss)
  - slow 80% grind: governors cut loss **−19.8% → −4.3%**, drawdown 19.8% → 4.3%
- **Walk-forward Optuna (12 trials, train 2022 / validate 2026):**
  - best TRAIN config **lost** out-of-sample (−1.18%) — overfitting caught
  - only the conservative config stayed positive + safe OOS → conservatism
    generalizes
- **Berserk adversarial battery (10 runs, ablations on real crashes):**
  - optimized candidate vs live: **live wins both windows** (candidate deployed
    ~2× capital in crashes) → candidate rejected via the review gate
  - age cap OFF → crash loss **doubles** (−1.5% → −3.0%) → cap earns its keep
  - lifecycle ≈ neutral in crashes (its value is chop/normal regimes)
  - ungoverned control: 3–5× deployment, 16 capitulations (−$524) vs **zero**
    governed → the exact trade-off the strategy refuses
- **Live dry-run (2 weeks):** ~90 closes, zero losing closes from profit paths;
  all losses were managed exits (drain/eviction ≤ ~1%); rotation, parking,
  brake, freeze all observed working in production.

## Expected behaviour (what you will see, and why it's correct)

- **Many small wins** (`grace_full_close`, `skim_*`): the core mechanic. ~75–95%
  of closes.
- **Some small managed losses** (`drain_close`, `age_cap_close`,
  `phase_d_close`): stuck capital being freed on schedule. Typically −0.2% to
  −3% each. **Not failures.**
- **Every deal dead or done by day 5** — nothing lingers past the age cap.
- **In a market dump:** crash freeze engages (log line: `CRASH FREEZE`), all
  buys stop, deals go sell-only, freeze releases with hysteresis (−2% + 6h).
  Expect reduced activity, not losses.
- **A coin falling beyond its own waves:** corridor brake latches it sell-only
  until its deal closes (log: `CORRIDOR BRAKE latched`). It never un-latches —
  by design.
- **Coins rotate:** score below the 2.0 quality floor → drain → retire → a
  better coin (or an empty slot) replaces it. Empty slots are correct behaviour
  when nothing clears the floor.
- **Display quirk:** FreqUI shows per-exit profit vs the blended average, so a
  profitable grid slice can display negative. Ledger truth ≠ display.
- **Current test:** 500 USDT dry-run wallet, $5 orders, $50/coin cap,
  **2-month evaluation started 2026-07-20** (fresh DB; prior history backed up
  as `tradesv3.sqlite.bak-pre500-20260720`). Success = drawdown control, clean
  rotation, no trapped capital — not headline profit.
