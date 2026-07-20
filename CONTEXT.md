# CONTEXT — WaveRider session state (reload this first)

**Purpose:** full working context for resuming after a context reset. Read this,
then `Analysis And Reports/rnd-sprint-context-digest.md` (sprint decisions +
findings), then DEVLOG.md TOP entry (newest-first) for anything newer.

**Last updated:** 2026-07-19 — post-R&D-sprint, berserk validation running.

## Current state (one screen)

- **Project:** WaveRider DCA crypto strategy on Freqtrade (Binance spot,
  dry-run). Purpose: escape bad deals profitably, never trap capital, capital
  safety before returns.
- **Everything lives in:** `C:\Users\ajay\Desktop\code by claude\` — now
  WaveRider-ONLY (other projects moved to `Desktop\other-projects\`).
- **Git:** local repo clean, branch `main`, ~14 commits, WaveRider-only history
  (rewritten; `refs/original` + `pre-cleanup-backup` hold pre-rewrite state).
  Remote `origin` = https://github.com/ajay42/waverider_evolved —
  **PUSH PENDING: Ajay must run `git push -u origin main` himself** (interactive
  GCM auth; Claude cannot complete the popup).
- **DEPLOYED TO CLOUD 2026-07-20:** Hetzner VPS `91.98.156.205` (Ubuntu 26.04,
  1vCPU/1.9G+2G swap), user `waverider`, SSH key `~/.ssh/waverider_deploy`
  (root disabled, key-only, firewall SSH-only, health cron, log rotation).
  Both containers running dry-run there. Project at `~/waverider/freqtrade`.
  Connection + FreqUI creds + go-live checklist in **DEPLOYMENT_CREDENTIALS.local.md**
  (git-ignored, this PC). LOCAL bot STOPPED — cloud is the single source of
  truth. Local machine = dev/backtest env only.
- **WENT LIVE (real money) 2026-07-20 ~15:46 UTC.** dry_run=false, real orders
  filling (KITE, PUMP first fills). Binance key: spot ON, withdrawals OFF,
  IP-locked to 91.98.156.205, futures/margin OFF (verified). DB was cleared of
  dry-run phantom trades before live start (backup tradesv3.sqlite.dryrun-bak-20260720).
  Real balance ~265 USDT (Ajay adding more toward 500). Base orders land at
  ~$7.5 (Binance min-notional bumps the $5 base). Helpers on server:
  set_keys.py, go_live.sh, verify_keys.py, check_perms.py. Emergency stop:
  `docker compose stop freqtrade`.
- **500-USDT TEST since 2026-07-20** (~2 months, to ~2026-09-20): target wallet 500,
  orders $5 (base_order_size_usd, via custom_stake_amount), per-coin cap $50,
  60% aggregate ceiling = $300 fresh. Success metric = drawdown control + clean
  rotation + no trapped capital, NOT profit. Berserk verdicts: live config
  final; candidate REJECTED (2× crash deployment); age cap proven (OFF doubles
  crash loss). First hours: sidecar selecting with quality floor working
  (left slots empty for sub-2.0 coins), base orders opening at $5.
- Next step (Ajay's flow): monitor the 2-month test; go live (Stage B) is a
  later deliberate step — Ajay adds spot-only/no-withdrawal/IP-locked Binance
  keys himself per the checklist.
- **R&D sprint (17→19 July): DONE.** All four deliverables built, tested,
  committed: synthetic stress tests (Tier A+B), walk-forward Optuna, win-prob
  model, offline relearn orchestrator. Plus the 5-DAY DEAL AGE CAP
  (`max_deal_age_days=5`, exit tag `age_cap_close`) — implemented, verified
  firing at exactly 5.0d, in live config + strategy default.
- **Sprint report:** `Analysis And Reports/rnd-sprint-report-2026-07-19.md`.
  Headlines: governors cut 80%-grind loss −19.8%→−4.3%; 5-day cap closes the
  wave-less-crash permanent trap; Optuna's aggressive train-winner LOST
  out-of-sample while conservative trial-8 stayed positive+safe (overfitting
  caught); honest verdict = capital-preservation strategy, not profit engine.
- **Candidate config:** `user_data/matrix_configs/candidates/20260719_candidate.json`
  (trial 8: brake 1.5→2.8, spacing 2→1.4, agg 60→50, dynamic ladder ON) —
  INERT proposal, never auto-applied. Recommendation: deploy current-live
  first; adopt candidate later via its review gate.
- **RUNNING NOW:** berserk validation (`run_berserk.py` → berserk_run.log,
  results `backtest_results/berserk/`): 5 variants (live / candidate /
  age_cap_off / lifecycle_off / no_governors) × 2 real crash windows
  (crash2021, bear2022b). ~3-4h. On completion: analyze with
  `analyze_tail.py --dir berserk`, fold into report addendum, ping Ajay.
- **New operator tools:** `weekly_summary.py` (weekly digest; separates managed
  capital-freeing exits from real losses), `STRATEGY_REFERENCE.md` (operator's
  manual), `freqtrade/CLOUD_DEPLOYMENT.md` (VPS plan; Ajay pays + enters API
  keys — spot-only, withdrawals OFF, IP-locked; compressed 2-3d cloud dry-run
  then small live fund).

## Operating rules in force

1. Build → test → commit (git). `test_sidecar.py` MUST pass before any
   strategy/sidecar decision-code deploy.
2. Docker batches ONE at a time (host crashed under concurrent load once).
   `MSYS_NO_PATHCONV=1` for container paths in Git Bash. Use `.replace()` not
   `.rename()` for Windows file moves.
3. Usage limits are top priority: file-based state (no heartbeat cron), big
   outputs to files, batch work into background Docker runs, model tiers
   (Sonnet/Fable routine, Opus for capital-safety code). Slow down / branch to
   lighter tasks if the limit nears; resume after reset.
4. Optimizations (fewer-coins/bigger-bet, dynamic sizing, param tuning) come
   AFTER core development; candidate configs only via the relearn review gate.
5. Reports → `Analysis And Reports/`; snapshots → `Code Backups/` before major
   strategy changes; keep LOGIC_FLOW.md updated.
6. Every terminal coin state needs its own entry-gate block (stint-enders:
   phase_d_close, drain_close, age_cap_close).
7. Simple language with Ajay; justify against the purpose; honest corrections.

## Next queue (after berserk)

1. Berserk report addendum + ping Ajay (running now).
2. Ajay pushes to GitHub; consider making repo private (strategy edge).
3. Cloud deploy per CLOUD_DEPLOYMENT.md (Ajay: VPS + keys; Claude: infra):
   2-3d cloud dry-run smoke → small live fund (spot-only, no-withdrawal,
   IP-locked keys, per-coin cap scaled down) → scale on proof.
4. Optimization phase (deferred): candidate adoption decision, concentration
   theory, per-coin sizing (P1-2), using berserk + weekly live data.

## Key learnings bank (don't relearn these)

- Freqtrade: `--datadir` used AS-IS (no exchange suffix appended); RemotePairList
  file:// needs FOUR slashes; `price_side: "other"` for market orders;
  backtest custom-data round-trips None as 'null' string (use typed coercers);
  informative pairs must read config directly (bot_start ordering); download-data
  needs `--prepend` to backfill older ranges.
- Windows: cp1252 console → reconfigure stdout utf-8; Path.rename fails on
  existing target → Path.replace; Git Bash mangles /paths → MSYS_NO_PATHCONV=1.
- Synthetic data: floor coin prices (8% of start) or beta>1 crashes hit ~0 and
  trip freqtrade's mandatory −99% stop backstop (fake stop_loss exits).
- Win-model: danger zones = price drawdown >10-15% and wave-age >12; wave score
  is a SELECTION edge, not a per-deal outcome predictor.
