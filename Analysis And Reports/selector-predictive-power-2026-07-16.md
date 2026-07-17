# Selector Soundness — Predictive-Power Study

**Date:** 2026-07-16 · **Question:** does the wave score *predict* future
waves, or only describe past ones? · **Method:** 26 historical dates
(bi-weekly, past 12 months), the whole Binance USDT universe scored AS OF
each date (identical formula to live, zero lookahead), then measured
against each coin's FOLLOWING week: how many skimmable 4h swings
(≥ 2.2% = take-profit + fees) it actually produced. 63+ coins per date
after volume floors; raw data in `user_data/selector_predictive_power.json`.

## Result: the score strongly predicts future wave supply

| score decile | avg score | skimmable waves the NEXT week |
|---|---|---|
| 1 (lowest) | 0.8 | 6.2 |
| 2 | 1.6 | 15.4 |
| 3 | 2.0 | 20.2 |
| 4 | 2.3 | 22.2 |
| 5 | 2.5 | 25.7 |
| 6 | 2.9 | 28.0 |
| 7 | 3.4 | 29.2 |
| 8 | 4.0 | 32.1 |
| 9 | 5.0 | 33.7 |
| 10 (highest) | 8.0 | **37.0** |

- **Perfectly monotonic** — every step up in score buys more future waves,
  no inversions across ten deciles.
- **Median per-date rank correlation: 0.806** — exceptionally strong for a
  financial predictor, and stable across dates (it held in bull, bear and
  chop weeks alike).
- Top-decile coins produce **6× the skimmable waves** of bottom-decile
  coins — the strategy's fuel supply is 6× richer where the selector
  points.

## Interpretation and consequences

1. **"Selection is the edge" is now a measured fact, not a thesis.** The
   score predicts exactly the quantity the strategy monetises.
2. **The quality floor (2.0) sits at the decile-3 boundary** — coins below
   it average ~15 waves/week vs 30-37 in the top deciles. The floor is
   well-placed; *raising* it toward ~2.5-3.0 is a legitimate stage-2
   experiment (fewer, better coins).
3. Wave *supply* ≠ profit by itself — the full chain (score → waves →
   skims → P&L) is closed by the cohort backtests (wave cohort +2.7…+4.1%
   vs volume cohort −0.5…+0.6% in the bear window) and 36 live closes.
4. Caveats: survivorship-lite universe (delisted coins absent — bounded by
   the volume floors); forward window = 1 week (matches typical stint
   length).

## Companion validations (same phase)

- Scoring math now covered by known-answer unit tests (sine/ramp/flat/young
  coin/volume median) in the pre-deploy gate.
- Remaining selector items queued: ingredient ablation, score stability,
  selector-doctor live audit, rotation replay.
