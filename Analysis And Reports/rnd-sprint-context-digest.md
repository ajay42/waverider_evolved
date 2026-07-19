# R&D Sprint — Context Digest (read this instead of scrolling chat)

**Purpose of this file:** a compact, self-contained reference of everything
decided and found in the 2026-07-17→19 R&D sprint, so a fresh session (or a
compacted context) can resume cheaply without re-deriving anything. Pairs with
CONTEXT.md (operational state) and DEVLOG.md (timeline). Last updated
2026-07-17.

---

## The mission
Deliver, before 2026-07-19, four capabilities on top of the Wave Rider DCA bot,
without weakening its purpose: **escape bad deals profitably, never trap
capital, capital safety before returns.**

## Operating rules in force (Ajay's, this sprint)
1. **Build → test → commit** each piece; heavy validation batched at the end.
   The ONE always-on gate: `test_sidecar.py` passes before any live
   strategy/sidecar decision-code change.
2. **Git-backed.** Secrets (config.json, *.sqlite, data/, logs/, backtest
   results, .venv-tools) are gitignored. One commit per finished component.
3. **Model tiers:** Sonnet/Fable for build/glue; full reasoning depth for
   capital-safety-critical code (governors, ladder math, lifecycle, entry/exit).
4. **No health-cron.** File-based state (CONTEXT/DEVLOG/this file). Docker does
   the compute at zero Claude cost; batches run ONE AT A TIME (host crashed
   under concurrent load once).
5. **Limits are top priority.** Adapt to avoid exhausting usage — a halted
   sprint is worse than a slower one. Pace sustainably; go hard only when it
   pays.
6. **Optimizations come AFTER core development** — fewer-coins/bigger-bet,
   parameter optimization, dynamic per-coin parameters are all deferred to the
   optimization phase (Step 6 below), tried only once the core is validated.

## NEW core rule (development, not optimization)
**No deal may stay open longer than 5 days.** Implement as a config knob
`max_deal_age_days` (default 5.0; 0 = off) — a hard absolute-clock backstop that
forces a deal sell-only and then closed by day 5, independent of wave count.
Rationale is data-driven (see findings): win rate collapses as deals age; 5
days (~8 waves at ~15h/wave) is tighter than the current wave-based decision
deadline (starts wave 12 ≈ 7.5d), so it becomes the effective time cap.
Accepts that some deals close at a loss — that is the cost of the no-trap
guarantee, consistent with "capital safety before returns." Its cost will be
QUANTIFIED in the synthetic + Optuna backtests. Must be applied AFTER the
stage-2 sweep finishes (so the sweep isn't run on a mixed strategy version),
then used by all subsequent validation runs. Gate: test_sidecar + smoke
backtest + Code Backups snapshot.

---

## The four deliverables — status + design

### Item 1 — Stress tests (two tiers)   [BUILT, backtests pending]
- **Tier A** (`wave_rider_dca/synthetic_paths.py` + `run_synthetic_sandbox.py`):
  fast, no-Docker parametric shock generator (depth/speed/recovery/waves) over
  the pure-Python reference. Ranks scenarios by capital-trap danger, writes
  `synthetic_shortlist.json` (6 curated shapes).
- **Tier B** (`gen_synthetic_data.py` + `run_synthetic.py`): re-expresses the 6
  shapes as real 1m/5m feathers (dedicated `data/binance_synthetic/`, real
  tickers, BTC as market factor so crash-freeze engages), backtests each
  governors-off vs all-on. Analyze via `analyze_tail.py --dir synthetic` and
  `monte_carlo.py`.

### Item 2 — Walk-forward Optuna optimizer   [BUILT + plumbing-validated, search pending]
- `run_optuna.py`: native freqtrade hyperopt can't split train/validate, so a
  custom host-side loop. Trials scored on TRAIN windows only; `--validate K`
  grades the best on held-out windows. Objective = mean profit − steep penalty
  for peak deployment >60% or drawdown >10% (can't buy return with tail risk).
  Study persisted to sqlite (resumable). Search space: ladder geometry,
  governor thresholds, quality floor, dynamic-ladder mults. Budget ~16 trials
  (framed honestly as "proven pipeline, partial run" — a half-converged config
  won't be promoted anyway). optuna 4.9.0 in `.venv-tools`.

### Item 3 — Win-probability model   [DONE + validated]
- `build_deal_dataset.py` → 16,259 trades from 53 zips, 100% enriched with
  as-of (lookahead-free) wave stats. `win_probability_model.py` → conditional
  win-rate tables + stdlib logistic regression, walk-forward (fit≤2022,
  validate≥2024). Outputs `win_probability_model.json`.

### Item 4 — Offline relearn orchestrator   [DONE + validated]
- `relearn_cycle.py` + `RELEARNING.md`: refresh model → read Optuna validation →
  emit ONE inert candidate config (diff vs live) through the safety gates, with
  a human deploy checklist. NEVER writes config.json or restarts a container.
  Live/online self-adjustment explicitly rejected for now.

---

## KEY FINDINGS (data-driven, load-bearing)

1. **The capital-trap condition (Tier A sandbox):** capital gets trapped ONLY
   when a crash has **no waves AND no recovery**. A wavy crash that recovers is
   where the strategy THRIVES (deep 60% wavy crash that recovers: 15 deals
   closed, +$33 skimmed, only $56 trapped). A smooth 70% crash with no waves and
   no recovery: 0 deals closed, $993 trapped at −52%. This directly validates
   the thesis ("waves are the fuel") and is exactly what the governors must
   blunt — Tier B measures how much they do.

2. **Deal-outcome danger thresholds (win-probability model, 16,259 trades):**
   - By phase: losses concentrate in `phase_d` (14% win, −$46 avg) and `forced`
     exits (1% win). Grace/skim/grid exits are ~100% win (profitable by
     construction).
   - **By price drawdown:** ~100% win until drawdown >10%, then 80% (10–15%),
     74% (15–25%), and **17% beyond 25%**. Clean monotonic collapse.
   - **By wave-age:** ~100% until ~12 waves, then **14% beyond 18 waves**.
   - Wave-score decile is nearly flat on per-deal OUTCOME (91–97%) — wave score
     is a SELECTION edge (which coins to trade, already proven by
     selector_predictive_power) more than a per-deal outcome predictor. Honest.
   - Model RANKS risk well (Brier 0.011 vs 0.054 baseline) but its absolute
     probabilities in the danger zone are mis-calibrated across eras (2021/2022
     training crashes harsher than the 2024–2026 validate period). So: good for
     ranking / threshold-setting, NOT yet trustworthy as live probabilities.
   - **These thresholds justify the 5-day cap** and any future capitulation
     tuning: act on drawdown-depth and age, not on wave score.

3. **Governors already proven (prior work, still standing):** on real historical
   crashes, all-governors-on cut peak deployment from 17–37% to ~6–7%
   (acceptance PASS), zero capitulations with the full stack.

---

## Remaining sequence (Docker-serial, event-driven)
1. Stage-2 sweep finishes (geometry comparison; on OLD strategy — fine).
2. Implement + test the 5-day deal cap; snapshot; it enters all later runs.
3. Synthetic Tier-B backtests (12 runs) → analyze.
4. Optuna search (~16 trials) → validate top-K out-of-sample.
5. Final validation pass (test_sidecar green, spot-checks) + sprint report to
   `Analysis And Reports/`.
6. THEN optimization phase (deferred): fewer-coins/bigger-bet, param + dynamic
   per-coin tuning driven by the Optuna results and win-model thresholds.

---

## Post-sprint directives (Ajay, 2026-07-19)

- **GitHub**: repo https://github.com/ajay42/waverider_evolved. Local repo
  cleaned to WaveRider-only (history rewritten to strip 3commas/accumulator/
  accumulator_bot/mean-reversion.pine/.claude; accumulator_bot preserved on
  disk untracked). Branch renamed master->main, 10 clean commits, no secrets.
  PUSH PENDING: needs Ajay's interactive GCM auth - he runs
  `git push -u origin main` himself (Claude's non-interactive shell can't
  complete the popup). refs/original + pre-cleanup-backup hold the pre-rewrite
  originals locally until push confirmed.
- **Go-live stance**: Ajay wants a SMALL LIVE FUND sooner (better teacher than
  paper). Compress pure-paper to a 2-3 day cloud dry-run smoke, then small live
  (spot-only, withdrawals OFF, IP-locked, small capital, per-coin cap scaled
  down). Plan in freqtrade/CLOUD_DEPLOYMENT.md. Ajay does: VPS payment + API
  keys. Claude does: all infra/automation.
- **NEW DELIVERABLES (build after validation, at the "end"):**
  1. BERSERK VALIDATION - aggressively test every theory/plan and logical
     deviations to prove worth (ablations, adversarial scenarios, param
     extremes, purpose-audit).
  2. weekly_summary.py - weekly trade-execution digest + improvement
     suggestions (file output, optional Telegram).
  3. STRATEGY REFERENCE CARD - a file summarizing the FINAL strategy in blocks
     + bullets, readable months later, with usage recommendations for the
     operator. Build AFTER berserk picks the final config.
  4. Cloud deployment (see CLOUD_DEPLOYMENT.md) - after all above green.
