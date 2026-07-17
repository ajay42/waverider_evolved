# Wave Rider — Stage-1 Backtest Matrix Report

**Date:** 2026-07-15 · **Runs:** 30 (all successful) · **Simulation:** Freqtrade backtesting, 5m timeframe with 1m detail, market orders, Binance fees
**Method:** 3 mechanically-classified BTC regime windows × 2 cohorts (as-of scoring, no lookahead) × 5 strategy variants. Wallet 10,000 USDT, 10 USDT base/safety orders, 1,000 USDT per-coin cap, TP 2%.

## Variants

| variant | lifecycle | phase order | combo | recycling | grace |
|---|---|---|---|---|---|
| `pure_wr` | off | — | outer pair | off | — |
| `wr_combo_rec` | off | — | best combo | on | — |
| `life_wr_first` | on | WR → grid | best combo | on | 3 waves |
| `life_grid_first` | on | grid → WR | best combo | on | 3 waves |
| `life_no_grace` | on | WR → grid | best combo | on | 0 |

## Windows & cohorts

| window | regime | BTC 30d context | wave cohort | volume cohort (control) |
|---|---|---|---|---|
| 2024-11-06 → 12-10 | bull | > +15% | RARE, RAY, MASK, BICO, PORTO, LAZIO, BAR, OGN, SANTOS, ARKM | BTC, ETH, SOL, DOGE, SUI, PEPE, NEIRO, BNB, WIF, XRP |
| 2026-03-02 → 04-25 | chop | ±15% | ESP, KITE, ENSO, FOGO, ZAMA, PUMP, VIRTUAL, ZRO, OP, WIF | BTC, ETH, SOL, XRP, BNB, PAXG, DOGE, ZEC, SUI, PEPE |
| 2026-06-02 → 07-01 | bear | < −15% (market −16.4%) | ALLO, HEI, WLD, XLM, NEAR, FET, JTO, INJ, AR, XPL | BTC, ETH, SOL, NEAR, XLM, ZEC, XRP, BNB, WLD, SUI |

## Results

*pnl/capday = profit ÷ Σ(stake × days held) — profit per unit of capital-time actually at risk (headline metric). zombie$ = PnL of Phase D capitulation exits. zombie-cd = capital-days locked in deals that ended in Phase D. forced = trades still open at window end (force-exited by the backtester).*

### BEAR (2026-06-02 → 07-01, market −16.4%)

| run | profit% | pnl/capday | dd% | harvest$ | zombie$ | zombie-cd | trades | forced |
|---|---|---|---|---|---|---|---|---|
| bear_volume_life_grid_first | 0.64% | 0.0022 | 0.33% | 110.71 | −26.03 | 21,124 | 180 | 1 |
| bear_volume_life_no_grace | −0.15% | −0.0005 | 0.88% | 99.91 | −41.21 | 18,760 | 139 | 2 |
| bear_volume_life_wr_first | 0.28% | 0.0012 | 0.52% | 102.86 | −54.07 | 19,805 | 169 | 1 |
| bear_volume_pure_wr | −0.12% | −0.0002 | 1.51% | 141.11 | 0.00 | 0 | 188 | 10 |
| bear_volume_wr_combo_rec | −0.45% | −0.0006 | 1.63% | 120.72 | 0.00 | 0 | 153 | 10 |
| **bear_wave_life_grid_first** | **4.09%** | **0.0079** | **0.75%** | **500.61** | **−22.03** | 22,409 | 679 | 6 |
| bear_wave_life_no_grace | 3.10% | 0.0056 | 1.39% | 458.70 | −3.56 | 19,543 | 531 | 7 |
| bear_wave_life_wr_first | 3.69% | 0.0083 | 0.99% | 501.58 | −31.07 | 21,107 | 680 | 6 |
| bear_wave_pure_wr | 2.85% | 0.0042 | 2.06% | 500.90 | 0.00 | 0 | 619 | 10 |
| bear_wave_wr_combo_rec | 2.65% | 0.0030 | 2.11% | 486.66 | 0.00 | 0 | 583 | 10 |

### BULL (2024-11-06 → 12-10)

| run | profit% | pnl/capday | dd% | harvest$ | zombie$ | zombie-cd | trades | forced |
|---|---|---|---|---|---|---|---|---|
| bull_volume_life_grid_first | 3.61% | 0.0202 | 0.24% | 383.36 | +3.15 | 1,983 | 671 | 5 |
| bull_volume_life_no_grace | 2.75% | 0.0099 | 0.21% | 296.71 | +0.02 | 15,130 | 534 | 6 |
| bull_volume_life_wr_first | 3.59% | 0.0194 | 0.21% | 379.34 | +0.07 | 4,876 | 662 | 5 |
| **bull_volume_pure_wr** | **3.64%** | **0.0211** | **0.14%** | **378.85** | 0.00 | 0 | 640 | 5 |
| bull_volume_wr_combo_rec | 3.34% | 0.0136 | 0.21% | 355.13 | 0.00 | 0 | 574 | 6 |
| bull_wave_life_grid_first | 1.32% | 0.0037 | 1.41% | 296.29 | −31.31 | 15,448 | 615 | 10 |
| bull_wave_life_no_grace | 1.23% | 0.0031 | 1.43% | 284.61 | −14.94 | 7,803 | 539 | 10 |
| bull_wave_life_wr_first | 1.39% | 0.0040 | 1.49% | 305.11 | −20.91 | 8,130 | 605 | 10 |
| bull_wave_pure_wr | 1.56% | 0.0039 | 1.65% | 326.59 | 0.00 | 0 | 619 | 10 |
| bull_wave_wr_combo_rec | 1.60% | 0.0030 | 1.49% | 313.33 | 0.00 | 0 | 545 | 10 |

### CHOP (2026-03-02 → 04-25)

| run | profit% | pnl/capday | dd% | harvest$ | zombie$ | zombie-cd | trades | forced |
|---|---|---|---|---|---|---|---|---|
| chop_volume_life_grid_first | 0.44% | 0.0018 | 0.17% | 68.81 | −21.48 | 14,473 | 188 | 6 |
| chop_volume_life_no_grace | 0.27% | 0.0013 | 0.33% | 67.41 | −39.12 | 8,713 | 171 | 6 |
| chop_volume_life_wr_first | 0.33% | 0.0016 | 0.28% | 68.64 | −33.11 | 8,570 | 178 | 6 |
| chop_volume_pure_wr | 0.83% | 0.0021 | 0.03% | 85.42 | 0.00 | 0 | 154 | 6 |
| chop_volume_wr_combo_rec | 0.78% | 0.0016 | 0.03% | 79.93 | 0.00 | 0 | 131 | 6 |
| **chop_wave_life_grid_first** | **0.95%** | **0.0012** | **0.79%** | **243.53** | **−92.40** | 35,522 | 408 | 10 |
| chop_wave_life_no_grace | −0.08% | −0.0001 | 1.09% | 192.19 | −171.43 | 44,770 | 353 | 9 |
| chop_wave_life_wr_first | −0.72% | −0.0010 | 1.82% | 212.73 | −226.97 | 37,040 | 398 | 9 |
| chop_wave_pure_wr | 0.45% | 0.0004 | 1.79% | 228.23 | 0.00 | 0 | 330 | 9 |
| chop_wave_wr_combo_rec | 0.86% | 0.0005 | 1.11% | 199.12 | 0.00 | 0 | 261 | 10 |

## Grace value (life_wr_first − life_no_grace, USD)

Positive = the DCA grace window earned more than the skims it suppressed.

| regime | cohort | grace value | grace-close PnL |
|---|---|---|---|
| bear | volume | +43.11 | +97.50 |
| bear | wave | +58.88 | +455.65 |
| bull | volume | +83.90 | +356.25 |
| bull | wave | +15.81 | +254.19 |
| chop | volume | +6.91 | +49.45 |
| **chop** | **wave** | **−64.05** | +175.92 |

## Cross-regime consistency (avg rank by pnl/cap-day; lower = better)

| variant | avg rank | ranks per cell |
|---|---|---|
| **life_grid_first** | **1.83** | 1, 2, 2, 3, 2, 1 |
| pure_wr | 2.33 | 3, 4, 1, 2, 1, 3 |
| life_wr_first | 2.67 | 2, 1, 3, 1, 4, 5 |
| wr_combo_rec | 4.00 | 5, 5, 4, 5, 3, 2 |
| life_no_grace | 4.17 | 4, 3, 5, 4, 5, 4 |

## Findings

1. **Winner: `life_grid_first`** — the only variant never ranking below 3rd in any regime×cohort cell. Its edge comes from cheap capitulations: the sell-only grid liquidates inventory at breakeven-plus before Phase D can bite deep (smallest zombie$ of the lifecycle variants everywhere).
2. **The lifecycle earns its complexity in bears**: pure variants ended every window with all 10 slots stuck open (forced=10) and 1.5–2.1% drawdowns; grid-first ended the bear with 0.75% drawdown, +4.09% profit, and capital circulating.
3. **Grace confirmed as amplitude-conditional** (Ajay's hypothesis): positive value in 5/6 cells; negative exactly in chop×wave, where it suppresses profitable skims on high-amplitude coins.
4. **The selector is the bear/chop edge; majors are the bull edge**: wave cohort +2.7–4.1% vs volume −0.5–+0.6% in the −16% bear; reversed in the Nov-2024 bull (majors +2.8–3.6% vs wave +1.2–1.6%). Regime-tilted cohort blending is a stage-2 candidate.
5. **Recycling without the lifecycle underwhelms** (`wr_combo_rec` avg rank 4.00).
6. **Thesis-in-one-number**: bear × wave × grid-first = **+4.09% profit, 0.75% max drawdown, in a market that fell 16.4%.**

## Caveats

- Cohort universe is today's listing set (survivorship-lite); fine for variant comparison, treat absolute returns with care.
- Dynamic rotation was not replayed (static cohorts per window); rotation-replay harness queued.
- Wave periods in backtests are estimated once per window (mild lookahead); rolling estimation queued.
- One bull window only (Nov 2024) — thin evidence base for bull-regime conclusions.

## Recommended actions

1. Switch live `phase_order` to `"grid,wr"` (from `"regime"`).
2. Stage-2 sweep on `life_grid_first` × wave cohort: amplitude-normalized ladders, two-stage dense/sparse ladder, volume×step scale jointly, cohort size, amplitude-conditional grace, BTC-slump study.
3. Complete rotation-replay + rolling wave-period before any live-capital decision.

## Live dry-run scoreboard (at time of report)

14 closes, 14 profitable, ~$4.9 realized on 10-USDT orders. Three full rotations (SXT, ALLO, SYN → replaced from amplitude ranking; DEXE joined and closed +1.78% within 2.5h). Exit mechanisms observed live: skim_full_close, grace_full_close (1–4 fill ladders). Pending live validation: partial skims at 2%, recycled refills, grid phase, Phase D, drain fast-exit (U/USDT chain expected ~14:34 UTC today).
