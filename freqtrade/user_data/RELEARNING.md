# Re-learning: offline-only, by design

This project has a "self-learning" capability, deliberately scoped to
**offline, periodic re-learning that produces a reviewed proposal** — never a
bot that changes its own parameters while trading.

## What it is

`scripts/relearn_cycle.py` runs one re-learn pass:

1. **Refit the evidence** — rebuild `analysis/deal_outcomes.csv` and the
   win-probability model (`win_probability_model.py`) on the latest backtest
   data.
2. **Re-optimize (walk-forward)** — optionally run new Optuna train-search
   trials (`--search N`), then grade the best on held-out validate windows.
3. **Propose, don't apply** — pick the best candidate that ALSO passes the
   capital-safety gates out-of-sample (peak deployment ≤ 62%, drawdown ≤ 12%),
   and write it to `matrix_configs/candidates/<date>_candidate.json` as an
   inert proposal with a diff against the live config.

## What it is NOT (and why)

It does **not** write `config.json`, and it does **not** restart any
container. A candidate is a suggestion on disk, nothing more.

A **live/online self-adjusting system** — the bot mutating its own live
parameters from recent performance — was **considered and rejected for now**.
Reasons:

- It cannot be safety-reviewed in the time we have, and this project's first
  principle is *capital safety before returns*.
- It would bypass the test-before-deploy gate that everything else honors
  (`test_sidecar.py` must pass; changes get backed up and human-applied).
- A feedback loop that tunes itself on recent data can chase noise straight
  into the next drawdown — exactly the failure the governors exist to prevent.

Revisiting online learning is possible later, but only as its own project with
its own safety review — not as a quiet extension of this script.

## Promoting a candidate to live (the gate)

A proposal is only ever applied by a human, following the checklist embedded in
each candidate file:

1. Review `diff_vs_live` — understand every changed knob.
2. `python user_data/scripts/test_sidecar.py` **must pass**.
3. Re-confirm the validate metrics (peak deployment ≤ 62%, drawdown ≤ 12%).
4. Snapshot the current `WaveRiderDCA.py` + `config.json` to `Code Backups/`.
5. Manually apply the diff to `config.json`.
6. `docker compose restart freqtrade`; watch the first cycle for errors.

If no validated candidate passes the safety gates, the correct outcome is
**no proposal** — never relax the gates to force one.
