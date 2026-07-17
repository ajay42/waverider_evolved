# Wave Rider DCA — Stage-1 Backtest Report

**Date:** 2026-07-15
**Scope:** First systematic validation of the Wave Rider strategy family — 30 backtests across 3 market regimes, 2 coin cohorts, and 5 strategy variants.
**Companion file:** `stage1-matrix-report-2026-07-15.md` (full result tables). This report adds the strategy/parameter background, test design, and complete reasoning behind the recommendations.

---

## 1. Executive summary

- **Winning variant: `life_grid_first`** — the full deal-lifecycle with the sell-only grid running *before* Wave Rider skims. It was the only variant never ranking below 3rd (of 5) in any regime×cohort cell, and it won outright where it matters most: **+4.09% profit with 0.75% max drawdown in a market that fell 16.4%**.
- **The coin selector is half the edge**: amplitude-selected coins beat the top-volume control by ~3.5 percentage points in the bear window — but lost to majors in the bull window, suggesting regime-tilted cohort blending as a future refinement.
- **The DCA grace window pays everywhere except high-amplitude coins in chop** (−$64 in that cell) — confirming the hypothesis that grace should become amplitude/regime-conditional.
- **The lifecycle's capitulation cost is real but cheap**: Phase D closes cost $22–92 per window in the winning variant, and in exchange the strategy ends windows with capital circulating instead of 10 frozen slots (the fate of every non-lifecycle variant).

---

## 2. Strategy background

### 2.1 Thesis

Most traders are eventually wrecked not by drawdowns but by **stuck deals** — capital frozen in positions waiting for a full retrace. Wave Rider inverts the usual design: it *deliberately* enters a "stuck" state with a very small base order, then treats **getting unstuck profitably** as the core competency. Volatility (waves) is the fuel; every wave is used to reduce exposure. The strategy consciously sacrifices trend profits for capital safety, and treats **zombie capital — not drawdown — as the enemy**.

### 2.2 Core mechanics (all validated in this test)

1. **Entry:** no signal — a flat coin immediately opens a small base order (BO). Always-in by design.
2. **Ladder:** safety orders (SOs) at pre-calculated price rungs (geometric spacing/sizing), computed once at BO, never ad-hoc. Every buy passes a hard per-coin capital cap; a rung that doesn't fit *waits*.
3. **Skim exits:** instead of one blended TP, the strategy closes the **combo of extreme fills** (oldest + newest, greedily extended to 3 while it lowers the combo's TP) whenever price recovers TP% past the combo's average — disposing of the *worst* inventory first, subsidized by the best. The book's quality improves with every skim.
4. **Recycling:** a partial skim closes 2–3 fills but reopens exactly **one** — the deepest closed rung — re-arming the counterweight so every wave can dispose of another old fill.
5. **Deal lifecycle** (phases change exit behavior only; capital rules never change):
   - **A — Grace:** classic DCA full-position TP (cheap trend-dip triage);
   - **B/C — Wave Rider and sell-only grid** in configurable order (grid = per-fill breakeven-plus liquidation ladder, no buys, deepest fill reserved as combo seed);
   - **D — Mechanical capitulation:** close small losses / extend once if the coin still waves / close. Every decision logged.
   - All phase boundaries are **wave-normalized** — measured in each coin's own wave period, not clock hours.
6. **Coin selection (sidecar):** rank the liquid universe by **wave amplitude** (avg 4h high-low swing %), optionally weighted by choppiness (1 − trendiness); gates for median-daily volume (pump-and-dump filter), spread, listing age. Coins retire after N deals per stint or when drained (stale/unproductive/capitulated) and slots refill from the ranking.
7. **Risk framework:** no leverage (spot only), no price stop-loss, hard per-coin cap, portfolio regime brake (no new BOs while BTC < −5%/24h), and the lifecycle time-boxes how long capital may hibernate.

### 2.3 Why these tests

Each mechanic was added through design debate, not evidence. Stage 1's job was to answer the **design questions** (which architecture?) before stage 2 spends compute on **parameter tuning** (which numbers?). Testing both at once with ~6 free parameters over one window is how strategies get curve-fit; the two-stage split with cross-regime consistency as the acceptance gate is the overfitting defense.

---

## 3. Parameter background

### 3.1 Held constant in all 30 runs (the capital-safety invariants)

| parameter | value | rationale |
|---|---|---|
| wallet (dry) | 10,000 USDT | — |
| base order / safety order #1 | 10 / 10 USDT | "cheap admission to the stuck state" |
| max safety orders | 15 | ladder ceiling |
| SO price deviation | 2.0% | rung spacing (static; amplitude-normalization queued for stage 2) |
| SO volume scale | 1.1 | geometric size growth (mild martingale) |
| SO step scale | 1.0 | even rung spacing |
| take profit | 2.0% | past combo/blended average |
| per-coin cap | 1,000 USDT | checked before **every** buy |
| max coins | 10 (static cohort) | rotation not simulated in stage 1 |
| deal restarts | effectively unlimited | rotation absent, so per-stint limits suspended |
| grid margin | 0.5% | per-fill exit level in grid/decision phases |
| Phase D | loss ≤ 15% → close; wave score ≥ 2 → extend once; else close | mechanical capitulation |
| wave-period fallback | in-strategy estimate from candles | sidecar absent in backtests |
| regime brake | off | no live ticker in backtesting |
| fees | Binance default (0.1%/side) | — |

### 3.2 Varied across variants (the design questions)

| variant | lifecycle | phase order | combo selection | recycling | grace |
|---|---|---|---|---|---|
| `pure_wr` | off | — | outer pair (original spec) | off | — |
| `wr_combo_rec` | off | — | best combo (greedy ≤3) | on | — |
| `life_wr_first` | on | WR → grid | best combo | on | 3 waves |
| `life_grid_first` | on | grid → WR | best combo | on | 3 waves |
| `life_no_grace` | on | WR → grid | best combo | on | 0 waves |

---

## 4. Test design

### 4.1 Regime windows — mechanically classified, not hand-picked

BTC daily closes since 2024-06; each day classified by trailing 30-day return (bull > +15%, bear < −15%, else chop); consecutive same-class days merged; windows ≥ 21 days kept (`find_regime_windows.py`).

| window | class | note |
|---|---|---|
| 2024-11-06 → 12-10 | bull | the only strong bull window in range |
| 2026-03-02 → 04-25 | chop | 55 days |
| 2026-06-02 → 07-01 | bear | market −16.4%; ended two weeks before this report |

### 4.2 Cohorts — as-of scoring, no lookahead

For each window's start date, the entire Binance USDT universe (435 symbols) was scored using **only candles ending at that date** (`build_cohorts.py`):
- **Wave cohort** = what the live selector would have picked: choppiness filter + amplitude×(1−trendiness) ranking + volume/age gates.
- **Volume cohort** (control) = plain top-10 by median daily volume — answers "does the selector add value?"

### 4.3 Simulation fidelity

- Freqtrade backtesting engine, 5m timeframe **with `--timeframe-detail 1m`** — intra-candle price paths matter for a strategy that reacts every ~5 seconds live; 5m OHLC alone would mis-time skims and rungs.
- Market orders with Binance fee model; per-fill ledger in trade custom data (identical code path to live).
- A **smoke test** (June bear, 4 majors) preceded the matrix and surfaced one real backtest-only defect (custom-data `None` round-trip), fixed and re-verified before any matrix run.

### 4.4 Known limitations (all tracked as follow-up tasks)

1. **Survivorship-lite universe:** cohorts drawn from today's listing set; delisted coins absent. Fine for *comparing variants*; treat absolute returns cautiously.
2. **Rotation not replayed:** static cohorts per window; the live system rotates coins continuously. A rotation-replay harness is queued.
3. **Static wave-period estimate** per window (mild lookahead); rolling estimation queued.
4. **One bull window** — bull-regime conclusions rest on thin evidence.
5. **`forced` exits:** trades still open at window end are force-closed by the backtester; counted separately so they don't masquerade as strategy exits.

---

## 5. Results

Full per-run tables live in `stage1-matrix-report-2026-07-15.md`. Digest:

### 5.1 Headline per regime (best runs)

| regime | best run | profit% | dd% | market |
|---|---|---|---|---|
| bear | wave × life_grid_first | **+4.09%** | 0.75% | −16.4% |
| bull | volume × pure_wr (grid_first within 0.03pp) | +3.64% | 0.14% | strong rally |
| chop | wave × life_grid_first | +0.95% | 0.79% | sideways |

### 5.2 Cross-regime consistency (avg rank by pnl/capital-day; the acceptance gate)

| variant | avg rank | worst rank |
|---|---|---|
| **life_grid_first** | **1.83** | 3 |
| pure_wr | 2.33 | 4 |
| life_wr_first | 2.67 | 5 |
| wr_combo_rec | 4.00 | 5 |
| life_no_grace | 4.17 | 5 |

### 5.3 Grace value (with-grace minus no-grace, USD)

Positive in 5/6 cells (+$7 to +$84); **negative exactly in chop×wave (−$64)** — grace suppresses profitable skims on high-amplitude coins in sideways markets.

### 5.4 The zombie ledger

- Non-lifecycle variants ended **every** window with all 10 slots stuck open (forced-exited by the backtester) and carried 1.5–2.1% drawdowns in the bear.
- Lifecycle variants paid bounded capitulation bills (−$3.56 to −$227 depending on variant/regime) and ended windows with 1–7 slots free and materially lower drawdowns.
- **Grid-first pays the smallest capitulation bills** of the lifecycle variants in every regime — the sell-only grid liquidates inventory at breakeven-plus *before* Phase D must close it at a loss. This is the mechanical source of its overall win.

### 5.5 Selector value

| regime | wave cohort (range) | volume cohort (range) |
|---|---|---|
| bear | +2.65% … +4.09% | −0.45% … +0.64% |
| chop | −0.72% … +0.95% | +0.27% … +0.83% |
| bull | +1.23% … +1.60% | +2.75% … +3.64% |

Amplitude selection is decisively the bear edge, mildly positive in chop (for the winning variant), and *counterproductive in the bull window*, where deep, cheap-spread majors harvested the rally better.

---

## 6. Recommendations

### Immediate (config-only)

1. **Set live `phase_order` to `"grid,wr"`** (currently `"regime"`). The fixed grid-first ordering beat the regime-picked ordering on the data.

### Stage-2 sweep (on `life_grid_first` × wave cohort as the base)

2. **Amplitude-normalized ladders** — rung spacing and TP as multiples of each coin's measured wave amplitude, frozen at BO. Replaces two hand-set constants with universal multipliers; prerequisite for running the strategy on low-amplitude majors (including the BTC-slump study).
3. **Two-stage dense/sparse ladder shape** — many tiny closely-spaced orders in the first wave-amplitude of depth (collectively significant, individually small), sparse larger rungs below; dense zone capped at ~20% of the per-coin cap. Resolves the grace-profitability vs small-BO tension without violating capital safety.
4. **Amplitude/regime-conditional grace** — disable or shorten grace for high-amplitude coins outside confirmed trends (the chop×wave fix).
5. **Joint `volume_scale × step_scale` sweep** — distance-weighting vs size-weighting as substitutes for counterweight power per committed dollar.
6. **Cohort-size sweep** (5×2000 / 10×1000 / 20×500 at constant total cap) — the concentration question, judged on pnl/capital-day *and* drawdown smoothness.
7. **Regime-tilted cohort blending** — majors-weighted list in confirmed bull, amplitude-weighted otherwise (from finding 5.5).

### Before any live capital

8. **Rotation-replay harness** and **rolling wave-period estimation** (close the two main simulation gaps).
9. **Execution hardening**: resting limit orders at rungs (the observed wick-miss), slippage measurement on larger SOs, ledger reconciliation for cancelled exits, order-book depth caps.
10. Extended dry-run of the stage-2 winner; live only after live matches paper. Capital-safety workstream (aggregate exposure governor, per-coin corridor brake — see `freqtrade/CAPITAL_SAFETY.md`) merges before sizing up.

---

## 7. Artifacts

| artifact | path |
|---|---|
| result zips (30) | `freqtrade/user_data/backtest_results/matrix/` |
| per-run configs | `freqtrade/user_data/matrix_configs/` |
| analyzer | `freqtrade/user_data/scripts/analyze_matrix.py` |
| matrix runner | `freqtrade/user_data/scripts/run_matrix.py` |
| cohort builder / regime finder | `freqtrade/user_data/scripts/build_cohorts.py`, `find_regime_windows.py` |
| cohort definitions | `freqtrade/user_data/cohorts/*.json` |
| architecture spec | `freqtrade/DESIGN.md` |
| full tables | `Analysis And Reports/stage1-matrix-report-2026-07-15.md` |

**Live dry-run at time of writing:** 14 closes, 14 profitable (~$4.9 on 10-USDT orders); three full rotation cycles; grace/skim exits validated at 1–4 fill depths; drain fast-exit and Phase-D re-entry gate deployed, awaiting the U/USDT drain validation.
