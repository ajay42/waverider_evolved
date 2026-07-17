# Wave Rider — Tail-Window Safety Report (Crash Tests)

> **CORRECTION (2026-07-16):** post-publication auditing found run 1's data
> foundation incomplete — Freqtrade silently skips merging OLDER date ranges
> into existing data files without `--prepend`, so each window was missing
> 1–4 cohort coins (worst: FTX window ran 7 of 11) and BTC everywhere (hence
> the inert freeze, finding 5). Within-window comparisons (brake vs none)
> remain valid — both sides saw identical data — but absolute numbers are
> understated and the freeze untested. Data repaired (`--prepend`), run-1
> results quarantined to `tail/run1-datagaps/`, and a clean 20-run sweep
> (m20/m25 arms dropped per finding 3) re-running. Addendum to follow.

**Date:** 2026-07-15 (late UTC) · **Runs:** 28/28 successful · **Purpose:** prove the capital-safety governors on history's worst weeks — the windows the strategy was *not* designed to profit in, only to survive.

**Verdict up front:** ACCEPTANCE **PASS** in all four crash windows — with governors on, worst-case concurrent deployment stayed between **4.3% and 7.2%** of the wallet (ceiling: 60%). The corridor brake is the decisive layer. One governor (the crash freeze) turned out to be **untested** due to a test-harness flaw found during analysis — documented below, fix + re-validation launched.

## Method

4 mechanically-classified crash windows × 7 governor variants, wave cohorts (as-of scoring, no lookahead), 5m sim with 1m detail:

| window | period | character |
|---|---|---|
| crash2021 | 2021-05-12 → 06-13 | May-2021 collapse (−50% BTC intramonth) |
| bear2022a | 2022-05-05 → 06-05 | LUNA collapse |
| bear2022b | 2022-06-13 → 07-12 | capitulation leg of the 2022 bear |
| ftxchop | 2022-09-17 → 11-08 | pre-FTX chop ending at the collapse |

Variants: `no_governors` (baseline) · `all_m15/20/25` (full stack, brake multiplier sweep) · `brake_only_m15` · `freeze_agg_only` · `all_m15_v105` (volume scale 1.05).

## Results (full tables in backtest_results/tail/)

### Acceptance — peak concurrent deployment, % of wallet

| window | governors OFF | governors ON (m15) | verdict |
|---|---|---|---|
| crash2021 | 33.1% | **6.1%** | PASS |
| bear2022a | 30.8% | **6.4%** | PASS |
| bear2022b | 20.5% | **7.1%** | PASS |
| ftxchop | 11.6% | **4.3%** | PASS |

### Key numbers per window (governed = all_m15 vs ungoverned)

| window | profit gov / ungov | max drawdown gov / ungov | capitulation bill gov / ungov |
|---|---|---|---|
| crash2021 | −2.88% / −3.14% | 3.08% / 4.63% | **$0** / −$471 (9 deals) |
| bear2022a | −2.95% / −8.13% | 3.04% / 8.21% | **$0** / −$822 (9 deals) |
| bear2022b | −0.13% / +2.68% | 0.97% / 0.49% | $0 / −$25 |
| ftxchop | +0.09% / +0.74% | 0.30% / 0.29% | $0 / −$36 |

### Monte Carlo (3,000 reshuffles, deal blocks — full output: user_data/mc_tail.txt)

Worst-case (99th pct) reshuffled drawdown, governed vs ungoverned: crash2021 **5.6% vs 8.5%**; bear2022a **5.1% vs 14.7%**. Caveat printed with every run: reshuffling under-counts correlation; real tails are worse than bands.

## Findings

1. **The corridor brake is the load-bearing governor.** `brake_only` ≈ full stack in every window. It cut deployment 3–5×, and — the strongest result — **eliminated deep capitulations entirely**: zero Phase-D closes in every governed run, versus capitulation bills of −$471 and −$822 in the violent windows ungoverned. The brake converts "ride the ladder to the bottom, capitulate at −31%" into "stop at the wave-break, harvest the bounce."
2. **The insurance premium is real and quantified.** In the two *milder* windows the ungoverned strategy earned more (+2.68% vs −0.13%; +0.74% vs +0.09%) — braking a coin that later recovers costs upside. In the two *violent* windows the governors cut losses by 8–64% and drawdown by a third to a half. That asymmetry — give up some upside in mild storms, get decisive protection in violent ones — is precisely the trade capital-safety-first demands.
3. **Brake multiplier: keep 1.5×.** m15 ≈ m20 everywhere; m25 measurably worse in crash2021 (latches too deep). The false-brake dial doesn't pay above 1.5 in crash regimes.
4. **Volume scale 1.05 is marginally safer than 1.10** across all windows (lower deployment and drawdown, similar profit) — consistent with the exposure model's prediction. Worth carrying into stage-2 as the safety-leaning default candidate.
5. **FLAW FOUND — the crash freeze was inert in ALL runs.** `freeze_agg_only` produced *identical* numbers to `no_governors` in every window, which is impossible if the freeze ever fired (May-2021 had −13%/24h days). Root cause: the regime reference (BTC) wasn't in the wave-cohort whitelists, and the backtest fallback read the *analyzed* dataframe, which only exists for whitelisted pairs — so the freeze signal returned "no data" for the entire sweep. Consequences: (a) every "all governors" result above is really **brake + ceiling only** — and they still PASS, so the acceptance stands; (b) the freeze itself remains backtest-unvalidated. **Fix implemented** (fall back to the raw informative candles) **and an 8-run re-validation launched** (`all_m15_fixed`, `freeze_agg_fixed` × 4 windows). Live behavior was never affected — the live freeze reads the exchange ticker directly.

## Decisions

- Governors stay ON live with `coin_brake_wave_mult: 1.5` (confirmed).
- `volume_scale 1.05` promoted to a stage-2 candidate default.
- Freeze verdict deferred to the fixed re-runs (report addendum to follow).
- The reserve-exclusion rule (built after this sweep started) is not covered by these runs; it joins the stage-2 test matrix.

## ADDENDUM — Run 2 on repaired data (2026-07-16, definitive)

20/20 runs on complete data (all cohort coins + BTC present, freeze functional
after the three-layer fix chain: informative flags read pre-config →
unsupported raw-data path → prefix column naming). **Every run-1 directional
conclusion survives; the numbers below supersede run 1.**

### Acceptance — peak deployment % (all governors vs none)

| window | OFF | ON | verdict |
|---|---|---|---|
| crash2021 | 36.7% | **6.8%** | PASS |
| bear2022a | 34.1% | **7.0%** | PASS |
| bear2022b | 20.4% | **6.2%** | PASS |
| ftxchop | 17.0% | **6.4%** | PASS |

### The freeze, finally measured (freeze+ceiling alone vs nothing)

- **LUNA window (bear2022a): −7.83% vs −9.85%** — the freeze alone saved ~2
  points and cut the capitulation bill from −$994 to −$870. In the most
  violent window it is genuinely protective on its own.
- crash2021: lower drawdown/deployment, slightly worse profit (−3.36% vs
  −2.71%) — froze through dips that bounced.
- Milder windows: costs some upside (bear2022b +1.00% vs +2.66%) — the
  familiar insurance premium.
- **On top of the brake, the freeze's marginal effect is small but risk-
  reducing** (all_m15 vs brake_only: equal-to-slightly-better drawdown and
  deployment everywhere). Verdict: keep it — cheap insurance whose value
  concentrates exactly where it matters (LUNA-class events).

### Governed worst cases (run 2 + Monte Carlo, 3k reshuffles)

Full-stack (m15): worst window profit −3.33%, worst drawdown 3.39%, zero
capitulations anywhere, 99th-pct reshuffled drawdown ≤ 5.6% of the wallet —
vs 17.1% ungoverned in the LUNA window. `v=1.05` again marginally safer than
1.10 in every window (promoted to stage-2 candidate default). Full MC:
`user_data/mc_tail_run2.txt`; run-2 zips in `backtest_results/tail/`.

## Artifacts

`backtest_results/tail/*.zip` (28) · `scripts/analyze_tail.py` · `scripts/monte_carlo.py` · `user_data/mc_tail.txt` · configs in `matrix_configs/`
