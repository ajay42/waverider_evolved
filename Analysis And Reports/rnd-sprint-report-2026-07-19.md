# WaveRider R&D Sprint — Final Report (2026-07-17 → 19)

Four capabilities delivered, plus a hard 5-day deal cap, all git-committed and
validated. This report is the honest, data-driven verdict: **what works, what
the strategy actually is, and what to do before real money.**

---

## TL;DR (read this if nothing else)

- **WaveRider is a capital-preservation strategy, not a profit engine.** Every
  independent test converges on this. Its edge is *surviving crashes* and *never
  trapping capital* — not making money in normal markets, where it grinds near
  break-even.
- **The safety stack works, on data it never saw.** On a slow 80% grind crash,
  the governors cut the loss from **−19.8% to −4.3%** and drawdown from 19.8% to
  4.3%. The new **5-day deal cap prevents the permanent capital trap** in the one
  scenario (wave-less crash) that would otherwise strand money forever.
- **Optimization caught overfitting.** The best *training* config *lost* money
  out-of-sample; the conservative one was the only one that stayed positive and
  safe. Conservatism generalizes — the whole thesis, proven with data.
- **Before real money:** judge the live fund on drawdown control and clean
  exits, not returns. If flat-to-slightly-positive-in-calm-markets with strong
  crash protection isn't the goal, this isn't the right strategy — and that's
  worth knowing now.

---

## 1. New core rule: the 5-day deal cap (`max_deal_age_days`)

A hard absolute-clock backstop above every lifecycle deadline: no deal stays
open past 5 days — it's force-closed (`age_cap_close`), loss accepted, capital
freed. Placed right after the drain fast-exit; mirrors the proven full-exit path;
ends the coin's stint so it can't instantly reopen.

- **Verified firing** (bear2022b smoke): 11 deals capped, all at exactly 5.0
  days, avg −3.07%, while 265 deals still closed profitably via grace → window
  net +1.53%. It caps the tail without wrecking normal profitability.
- **Data justification:** the win-model shows win-rate collapses as deals age
  past ~12 waves; 5 days (~8 waves) caps *before* that cliff.

## 2. Synthetic crash stress tests (Tier A + Tier B)

Beyond-history shock shapes (depth/speed/recovery/waves), first curated by a
fast no-Docker sandbox, then run through the *full live system* on synthetic
1m/5m data (real tickers, BTC as market factor so crash-freeze engages).

**Governors ON vs OFF — peak deployment held on all 6, and the flagship:**

| Scenario | Loss OFF | Loss ON | DD OFF | DD ON |
|---|---|---|---|---|
| grind_80_slow_wavy | −19.8% | **−4.3%** | 19.8% | **4.3%** |
| (others: low deployment, governors idle by design) | ~0% | ~0% | — | — |

- **The capital-trap condition** (from Tier A, confirmed): capital traps *only*
  when a crash has **no waves AND no recovery**. A wavy, recovering crash is
  where the strategy *thrives* (skims out at a profit).
- **smooth_70_no_waves** (the pure trap): without the 5-day cap this strands
  capital forever; with it, deals exit cleanly at ~0% — the trap is closed.
- Data-integrity note: an earlier run showed `stop_loss` exits because
  high-beta synthetic coins hit ~0 price and tripped Freqtrade's −99% backstop;
  fixed by flooring coin prices at 8% of start. Final run: **0 stop_loss exits.**

## 3. Win-probability model (16,259 trades, as-of enriched)

Interpretable conditional win-rate tables + logistic cross-check, walk-forward
(fit ≤2022, validate ≥2024).

- **Danger thresholds (monotonic, actionable):** win-rate ~100% until price
  drawdown >10%, collapsing to **17% beyond 25%**; ~100% until wave-age >12,
  collapsing to **14% beyond 18 waves**. Losses concentrate in Phase-D
  capitulations and forced exits — by design.
- Wave-score is a *selection* edge (which coins), not a per-deal outcome
  predictor. Model ranks risk well (Brier 0.011 vs 0.054 baseline) but its
  absolute probabilities in the danger zone need era-aware recalibration before
  any live use.

## 4. Walk-forward Optuna optimization

Custom host-side loop (native hyperopt can't split train/validate). Safety-first
objective: profit penalized hard for deployment >60% or drawdown >10%.

- **The overfitting lesson:** highest train score (trial 1, 55% deployment) →
  **−1.18% out-of-sample**. The conservative trial 8 (11% deployment, tighter
  brake) → **+0.04% OOS, dd 0.5%** — the only one both positive and safe.
- **Candidate produced** (inert proposal, `20260719_candidate.json`, NOT
  applied): more conservative than live — brake mult 1.5→2.8, spacing 2.0→1.4,
  agg ceiling 60→50, dynamic per-coin ladder OFF→ON. Review the diff before any
  adoption.
- Absolute OOS profit is tiny (+0.04% over ~2 months) — reinforces §TL;DR: this
  preserves capital, it doesn't multiply it.

## 5. Offline self-learning (relearn orchestrator)

`relearn_cycle.py`: refresh win-model → read Optuna validation → emit ONE
candidate config through the safety gates, with a human deploy checklist.
**Verified end-to-end: produced the candidate above without touching
config.json.** Live/online self-mutation deliberately rejected (would bypass the
test-before-deploy gate and can chase noise into drawdown).

## 6. Honest limitations

- Backtests have no order-book: slippage/partial-fills/latency unmodeled. Paper
  is optimistic — the small live fund is exactly how we measure that gap.
- Validation is 2 held-out windows (small sample); the overfitting signal is
  directional, not definitive.
- Synthetic shocks are parametric, not real market microstructure.
- Returns are thin; the value proposition is drawdown control.

## 7. Recommendations

1. **Deploy the *current* live config first**, not the candidate — prove the
   base system on a cloud small-fund before layering the (more aggressive-ladder)
   candidate on top. Adopt the candidate later via its review gate.
2. **Size the live fund so worst-case is a tuition fee** (per-coin cap scaled to
   the fund). Judge it on drawdown, not return.
3. **Front-load liquidity** for the first live weeks (higher-liquidity coins).
4. **Keep the offline-relearn discipline** — never live-tune on recent results.
5. Next: the "berserk" validation (candidate-vs-live on the full crash battery,
   governor ablation, adversarial extremes) before any go-live.

---
*Artifacts: `backtest_results/{synthetic,optuna}`, `win_probability_model.json`,
`optuna_validation.json`, `matrix_configs/candidates/20260719_candidate.json`.
Reproduce via the scripts in `user_data/scripts/`.*
