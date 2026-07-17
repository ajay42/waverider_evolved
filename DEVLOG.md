# Wave Rider — Development Log (48h autonomous mission)

**Mission started:** 2026-07-15 ~15:45 UTC · **Ends:** 2026-07-17 ~15:45 UTC
**Mandate from Ajay:** develop, test, evolve, stress-test, check logic/purpose
adherence, backtest, review code structure and efficiency, plot graphs, test
again. Mission-critical rigor. Backups at major iterations only. Ping Ajay in
easy language only when a real choice needs his input.

**The purpose everything is checked against:** get out of bad deals
profitably, never let capital get trapped, waves are the fuel. Capital safety
before returns.

## Plan (in priority order)

1. **Crash tests (running):** 28 tail-window backtests through 2021/2022
   crashes → safety report + PASS/FAIL on the 60% deployment ceiling.
2. **Monte Carlo:** luck-testing on all results (script ready, smoke-tested).
3. **Stage-2 tuning, walk-forward style:** ladder spacing/size sweep +
   amplitude-scaled ladders + two-stage dense/sparse ladder — tuned on old
   windows, graded on unseen ones.
4. **Unit tests** for the pure math (ladder, combo selection, phase clock) —
   mission-critical code should not depend on eyeballing.
5. **Code structure & efficiency review** of the strategy file (~1,200 lines).
6. **Graphs:** equity curves and drawdown charts for the reports.
7. **Synthetic-crash Monte Carlo** using the simple reference simulator —
   stress beyond recorded history.
8. **Logic/purpose audit:** walk LOGIC_FLOW.md against DESIGN.md and the live
   behavior; document any drift.
9. Live dry-run keeps validating in parallel (ZBT wind-down, U drain,
   phase transitions).

## Rules I'm holding myself to

- CONTEXT.md at the project root is the session recovery point — update it
  at every milestone (Ajay's request, 2026-07-15 19:40).

- Backup to `Code Backups/<date>-<milestone>/` before each major change only.
- Every meaningful event gets a timestamped entry below.
- Any fork in the road that changes strategy behavior → ping Ajay with a
  simple question, keep working on non-blocked items meanwhile.
- No new features that don't serve the purpose. Validation beats invention.

---

## Timeline (UTC)

- **2026-07-17 16:40** — R&D SPRINT DAY 1 (to 2026-07-19). Operating model:
  git-backed build->test->commit, model-tier discipline, no health cron
  (file-based state), Docker does the compute. Progress:
  - **Git baseline** committed (secrets/config/sqlite/data/logs gitignored;
    verified no jwt key or password staged — the Code Backups snapshots'
    config.json copies were caught and excluded).
  - **Stage-2 sweep relaunched** after the reboot crash; resumed correctly
    from run 4/18, skipping the 3 completed. Running in background.
  - **Item 1 Tier A (synthetic stress sandbox)** — DONE. Parametric shock
    generator (depth/speed/recovery/waves) over the pure-Python reference.
    Confirms the purpose model cleanly: capital traps ONLY when there are
    no waves AND no recovery; wavy recovering crashes let the strategy skim
    out (crash_60_v_recover: 15 closes, +$33, $56 trapped vs
    smooth_70_no_waves: 0 closes, $993 trapped at -52%). Curated 6-scenario
    shortlist for Tier B.
  - **Item 3 (win-probability model)** — DONE + validated. 16,259 trades
    from 53 zips, 100% enriched with as-of (lookahead-free) wave stats.
    Walk-forward (fit<=2022, validate>=2024). FINDINGS worth acting on:
    losses concentrate in phase_d (14% win) + forced exits; win rate ~100%
    until price drawdown >10%, collapsing to 17% beyond 25%; ~100% until
    wave-age >12 waves, collapsing to 14% beyond 18. Model ranks risk well
    (Brier 0.011 vs 0.054 baseline) but absolute probabilities in the
    danger zone are mis-calibrated across eras (train crashes harsher than
    the validate period) — good for ranking, needs recalibration before
    any live wiring. NOT wired to live decisions (out of scope by design).
  - **Item 2 (walk-forward Optuna optimizer)** — BUILT + plumbing validated
    (study resumable, safety-first objective correct on a real zip, param
    space sampled). optuna 4.9.0 installed in host venv. Search NOT yet
    launched — waits for the stage-2 sweep to free the Docker daemon.
  - Fixed LOGIC_FLOW drain-line doc drift (0.2->1.0%).
  Remaining Day 1->2: Item 1 Tier B (real governor backtests on the
  shortlist), Item 4 (offline relearn orchestrator), launch Optuna search,
  validate top-K out-of-sample, final validation pass + sprint report.

- **2026-07-17 17:15** — ALL FOUR DELIVERABLES BUILT + COMMITTED (git, one
  commit each). Item 1 Tier B: gen_synthetic_data.py materializes the 6
  shortlisted shock shapes as real 1m/5m feathers (deep crashes verified,
  BTC as market factor so freeze engages), run_synthetic.py backtests
  governors-off vs all-on, analyze_tail.py gains --dir reuse. Item 4:
  relearn_cycle.py + RELEARNING.md - offline-only, emits inert candidate
  proposals through the safety gates, never writes config.json. optuna
  4.9.0 + pandas/pyarrow installed in gitignored .venv-tools. Everything's
  no-Docker parts are tested green. REMAINING is purely Docker-serial
  (run one batch at a time - this host crashed under load once): finish
  stage-2 sweep (on run 5/18) -> synthetic 12 runs -> Optuna 16-trial
  search + validate -> final pass + sprint report to Analysis And Reports.
  Sequenced event-driven off task-completion, not polling.

- **2026-07-17 03:55** — RESOURCE POLICY SET, closing out the usage-limit
  crisis that started earlier today: per-trade live monitors removed, the
  2h heartbeat replaced with a 4h one, then that cancelled outright
  (`fed4ed42` deleted) while Ajay decided the real fix. Landed on: (a)
  model policy — Ajay runs Opus/high-effort as his own default; Claude
  scales Sonnet/Fable for its own work (subagent spawns), matched to task
  difficulty, EXCEPT anything touching capital-safety-critical code (the
  three governors, ladder math, lifecycle phases, entry/exit gating) which
  always gets full reasoning depth regardless of cost — correctness beats
  convenience on critical components; (b) heartbeat recreated at 8h,
  scoped to MISSION-CRITICAL-ONLY checks (containers up, governor
  trips/errors in both logs, exposure vs ceiling) and silent unless
  something needs attention — no more routine trade digests; (c) Ajay's
  Claude usage is fully dedicated to this project for now; (d) adaptive
  throttling defined — Claude can't read the actual 5h usage meter, so the
  downshift trigger is Ajay flagging it or clear proxy signs (frequent
  compaction, slow turnaround), and downshift means pausing new heavy
  sweeps/subagent work until Ajay confirms the limit reset. CONTEXT.md
  updated to match. Also corrected CONTEXT.md's resume checklist: this
  file is newest-first (new entries go right here, after the header), not
  append-at-bottom as it previously said — a real bug, since a fresh
  session following the old instruction would have read the oldest entries
  first. Side-finding while wiring the new heartbeat: Docker Desktop had
  just restarted (machine reboot) and the daemon wasn't up yet when first
  checked — waited ~50s, both containers (`freqtrade`, `freqtrade-pairlist`)
  came back on their own via the compose restart policy, no manual
  intervention needed. Good evidence the mission-critical trading stack
  self-heals across a reboot independent of any Claude session being open.

- **2026-07-16 23:50** — STAGE-2 LAUNCHED (18 train runs, ~10h), now
  including AJAY'S BEST-COINS EXPERIMENT: top-5 cohorts (only the best
  signals) x {standard geometry | dynamic per-coin geometry at two
  strengths}. New strategy capability built + tested for it:
  dynamic_ladder_enabled - each deal's rung spacing and take-profit set
  from THAT coin's measured amplitude at deal start (clamped 0.8-5%),
  frozen per deal, still pre-calculated. Per-coin position SIZING
  deliberately deferred (needs the P1-2 sizing framework; bolting it on
  against the clock would violate the caps' invariants). Walk-forward
  discipline: train 2022, validate 2026 after inspection. CONTEXT.md
  updated per Ajay's request.
- **2026-07-16 17:25** — SELECTOR VERDICT: THE SCORE PREDICTS THE FUTURE.
  Predictive-power study complete (26 dates x whole universe, no
  lookahead): decile table perfectly monotonic - bottom-decile coins
  produced 6.2 skimmable waves the following week, top-decile 37.0 (6x),
  median per-date rank correlation 0.806. "Selection is the edge" is now a
  measured fact. Bonus finding: the 2.0 quality floor sits right at the
  decile-3 boundary; raising toward 2.5-3.0 is a legit stage-2 experiment.
  Report: Analysis And Reports/selector-predictive-power-2026-07-16.md.
  Stage-2A geometry sweep (deviation x volume-scale, walk-forward: train
  2022 windows, validate 2026) prepared; launch pending a permission-
  service blip retry.
- **2026-07-16 16:30** — SELECTOR SOUNDNESS PHASE STARTED: (a) scoring-math
  unit tests added with known-answer synthetic candles (sine wave -> right
  period + untrendy; ramp -> trendiness 1; flat -> zero amplitude; young
  coin -> rank-last sentinel; volume median math) - all pass, now part of
  the pre-deploy gate; (b) the predictive-power study LAUNCHED in the
  background: 26 historical dates x whole universe, score-as-of vs the
  NEXT week's skimmable waves, decile table + rank correlation - the
  "does our score know the future?" answer, ~45-60 min. Live: SNDKB
  braked (4th case, floor-triggered), SENT +2.02%.
- **2026-07-16 15:45** — RUN-2 CRASH SWEEP COMPLETE (20/20) — DEFINITIVE
  SAFETY VERDICT: acceptance PASS in all four windows (deployment 17-37%
  ungoverned -> 6-7% governed), zero capitulations with the full stack,
  worst governed window -3.33% profit / 3.39% dd while ungoverned LUNA
  replay hit -9.85% / 9.93%. Freeze finally measured: alone it saved ~2pp
  and $124 of capitulations in the LUNA window (its home turf); on top of
  the brake its margin is small but risk-reducing everywhere - kept.
  v=1.05 again safer everywhere. Report addendum written; MC bands
  captured (governed 99th-pct reshuffle dd <=5.6% vs 17.1% ungoverned).
  Live during the same hours: PUMP x2 wins, ALLO rejoined after cooldown
  and won (+2.05%), DODO braked and peeling. 36 closed deals, +$4.9.
- **2026-07-16 09:20** — SESSION INTERRUPTION AUDIT (usage-limit restart):
  damage = nearly zero. The trading bot and picker never blinked (Docker
  is independent of my session; 0 errors; DODO +1.76% and a MUB drain
  eviction happened normally during the blind window). The 20-run crash
  sweep SURVIVED as an orphaned host process - 15/20 done, run 16
  executing, ~3h remain. Lost: my log monitors (session-scoped) -
  re-armed, plus a completion watcher on the sweep log. Heartbeat cron
  survived. CONTEXT.md recovery design worked as intended.
- **2026-07-16 05:35** — FREEZE ALIVE, THIRD FIX WAS THE CHARM: the merged
  reference column is PREFIX-named (btc_usdt_ref_5m), not suffix-named as
  assumed — one wrong string kept the signal invisible. With name-agnostic
  lookup: three clean engage/release cycles across the May-2021 crash week
  (engage -5.1%, 13h dwell, release -2.0%; then 24.9h and 6h cycles), and
  the week's loss HALVED vs freeze-dead (-1.73% vs -3.33%). Debug probes
  stripped, sidecar tests pass, snapshot 2026-07-16-freeze-fix, live bot
  redeployed on fixed code, clean 20-run crash sweep LAUNCHED (~9h).
  Bug-chain postmortem for the audit: three stacked silent failures
  (informative flags read pre-config; raw-data path empty in backtests;
  column naming) — each "fix" looked plausible and changed nothing, only
  the identical-results red flag kept the investigation honest.
- **2026-07-16 05:30** — DATA-GAP DISCOVERY + honest correction: chasing
  the inert freeze led to the real root cause — freqtrade doesn't merge
  OLDER date ranges into existing data files without --prepend, so the
  crash windows were missing BTC everywhere plus 1-4 cohort coins per
  window (FTX window ran 7 of 11 coins). Run-1 verdicts: within-window
  comparisons stand (both sides saw the same data); absolute coverage was
  thin; freeze untested. Fixes: (a) --prepend re-download of all missing
  history (verified: BTC 2021 rows present), (b) freeze signal rewired a
  third time - now rides INSIDE each traded pair's dataframe via the BTC
  informative merge (the only path backtesting truly supports; attempts
  1-2 read paths that are empty in backtest mode), (c) run-1 results
  quarantined, (d) slimmed 20-run re-sweep prepared (m20/m25 dropped).
  Diagnostic on the May-19-2021 crash day: behavior changed decisively
  with the signal flowing (-0.10% vs -5.95% on identical days), freeze
  engagement line pending a window with pre-crash open deals. Report
  carries a correction banner. Lessons: (1) silent data gaps are the
  deadliest backtest failure - a coverage audit now precedes any sweep;
  (2) identical-to-baseline results are a red flag, not a coincidence.
- **2026-07-16 00:10** — CRASH TESTS COMPLETE: 28/28 runs, ACCEPTANCE PASS
  in all four windows (deployment 21-33% ungoverned -> 4-7% governed; the
  corridor brake eliminated ALL deep capitulations: $0 vs -$471/-$822
  bills). Insurance premium quantified: governors give up upside in mild
  windows, cut losses/drawdown decisively in violent ones. Brake mult 1.5
  confirmed; v=1.05 marginally safer. Monte Carlo bands captured. FLAW
  FOUND during analysis: the crash FREEZE was inert in the whole sweep
  (freeze_agg_only ≡ no_governors exposed it) — BTC wasn't whitelisted in
  wave cohorts and the backtest signal read only whitelisted pairs' data.
  Fix shipped (raw informative candles fallback); 8-run re-validation
  launched (all_m15_fixed / freeze_agg_fixed × 4 windows). Live freeze was
  never affected (ticker path). Full report:
  Analysis And Reports/tail-safety-report-2026-07-15.md
- **2026-07-15 21:28** — MILESTONE: first corridor-braked deal completed
  its FULL wind-down, profitably. DEXE: joined 07:36, laddered to 6 fills
  ($71), fell ~7%, BRAKE latched ~19:45 (sell-only forever), then the
  recovery let the grid peel all six slices over ~1.5h (last slice +6.3%),
  ending grid_full_close. FINAL DEAL RESULT: +0.53% (+$0.38) — a deal that
  was 7% underwater and locked from buying still closed net positive,
  purely via per-fill exits into the bounce. This is the strategy's core
  promise ("get out of bad deals profitably") demonstrated end-to-end by
  the safety machinery itself. Note: brake is per-DEAL; DEXE the COIN
  remains listed (score 6.4, best on the list) and may open a fresh deal
  at the new price level — by design; watching.
- **2026-07-15 19:50** — Score visibility shipped (Ajay's ask): (a) chart
  gains a "quality" pane — the coin's current wave score vs the 2.0 floor;
  (b) scripts/status.py prints the whole-list monitoring table (score,
  amplitude, wave period, stint age, PARKED/DRAIN/BRAKED flags, open
  position). First run of the table surfaced: DEXE corridor-braked (~12h
  after joining, $71 exposure) — braked but NOT parked because the parking
  cap (3) is full with ZBT/CRV/HEI, exactly the bounded behavior designed.
- **2026-07-15 19:45** — RESERVE EXCLUSION shipped (Ajay's design + bounds):
  parked capital no longer counts against the 60% working budget, up to
  20% of wallet — the reserve now underwrites the workout bags so the
  post-crash bounce gets the FULL working budget. Exemption sleeps during
  a crash freeze and for 6h after release (never fuels a falling market).
  Hard untouchable floor by construction: 20% of wallet. Same rule
  mirrored in the sidecar's refill gate. ALSO fixed the joiner
  inconsistency Ajay's screenshot exposed: candidates must now clear the
  same 2.0 quality floor as members — first live effect visible
  immediately: "refill stopped: AAVE scores 1.94 below the floor - slot
  stays empty." The three sub-floor admits (AAVE/ZEC/ADA) already rotated
  out for pennies. Sidecar tests passed pre-deploy (new standing rule
  honored). CONTEXT.md updated.
- **2026-07-15 19:25** — PARKING SHIPPED + a regression caught and fixed
  within 20 minutes. (a) Slot parking live per Ajay's design: deals that
  can never buy again (braked / draining / decision-age) stop consuming
  trading slots; list grew 10 -> 13 (AAVE, ZEC, ADA joined); safety package
  active (max 3 parked, refills blocked over 45% deployment or BTC crash,
  quality floor). ZBT/CRV/HEI parked; ~$400 of stuck capital no longer
  blocks fresh opportunity. (b) REGRESSION: my parking patch dropped the
  closed-trades branch in the sidecar's DB reader -> all earnings read
  $0.00 -> profit-drain wrongly evicted-marked SENT (a coin earning
  $0.33/day). Caught via the suspicious log line, SENT protected before
  eviction, branch restored, verified. (c) First unit tests written
  (test_sidecar.py, 5 checks on the decision math) - mission step 4
  started early, motivated by exactly this incident. Lesson: string-patch
  edits to decision code REQUIRE the test run before deploy; adopted as
  standard practice for the rest of the mission.

- **2026-07-15 19:35** — Chart change per Ajay: magenta now marks EVERY
  order that has an armed exit target, in every phase/mode (all fills in
  grace, the 1-3 combo in wave-riding, each eligible fill in grid/lockdown;
  up to 6 shown, deepest first). Queued: stepped historical lines (levels
  drawn from when they became true, not repainted flat) — after the crash
  report. Also corrected a false alarm: the "hung sidecar" was a timezone
  misread on my part; it never missed a cycle. INJ retired properly, UNI
  joined (score 2.34).
- **2026-07-15 18:50** — Quality floor's first catch, 20 minutes after
  deployment: INJ's wave score slipped to 1.92 (< 2.0) → drained → evicted
  at −0.04% (essentially free). Note INJ had earned two wins earlier — the
  floor evicts on fading QUALITY, not past performance, which is exactly
  the "pick from the list each time" behavior Ajay asked for. U and XAUT
  retired cleanly; SNDKB and MUB joined from the ranking. All three of
  today's new mechanisms (quality floor, drain eviction, retired-block)
  observed working live.
- **2026-07-15 18:40** — Ajay's design change, analyzed and deployed:
  3-runs-per-coin rule REMOVED. Winners stay as long as they stay good.
  Live evidence supported it (we fired SXT/ALLO/SYN/TOWNS mid-winning-streak),
  and every backtest already ran without the limit. Its safety job passes to
  a new QUALITY FLOOR: the picker now re-scores active coins every cycle and
  drains any whose wave score drops below 2.0 — rotation is quality-driven,
  not counter-driven. LOGIC_FLOW.md updated. Watch item: rotation frequency
  should fall; slot occupancy by top scorers should rise.
- **2026-07-15 18:15** — BUG (caught by Ajay) + FIX: U and XAUT reopened
  fresh deals seconds after their drain evictions. Cause: retiring a coin
  clears its "draining" mark ~minutes before the tradeable list actually
  drops it (5-min refresh lag) — in that gap the door-check let them back
  in. Fixed two ways: (1) retired coins are now explicitly blocked at the
  door, (2) a drain eviction now ends the coin's stint outright, same as a
  capitulation. Escapee deals evicted again (−0.19%, −0.22%), no third
  reopen — verified. Lesson recorded: every terminal state (retired,
  capitulated, drained) must have its own door-block; never rely on list
  membership timing. Ajay directive noted: COIN SELECTION IS THE EDGE —
  selector quality work moves up the priority list (selection-quality
  metrics fold into stage-2; rotation replay right after).

- **2026-07-15 15:45** — Mission start. Tail backtests running (28 runs,
  ~10 done by now). Monte Carlo script written and smoke-tested on stage-1
  results — winner (`life_grid_first`) shows ≤0.8% worst-case dip at the
  99th percentile in bear windows; rejected variants show 50–68% chance of
  loss under reshuffling, confirming stage-1's verdict.
- **2026-07-15 15:45** — Simple-code backup created:
  `Code Backups/simple-reference-wave-rider/` (the original pure-Python
  Wave Rider simulator + the one-page LOGIC_FLOW pseudocode). This is the
  "check the logic without reading 1,200 lines" kit.
- **2026-07-15 15:40** — Live: ZBT braked bag winding down (12 fills, $195);
  ALLO/SYN/TOWNS/SXT rotations complete; 17 profitable closes, 0 losing.
- **2026-07-15 17:20** — Ajay's call: drained-coin quick eviction widened
  from 0.2% to 1% tolerated loss. Result was immediate: U and XAUT closed
  within a minute of the restart (drain_close, pennies of realized loss),
  their slots now free for rotation. This also fixes the "slow-wave coins
  squat longest" gap — U's 48h waves would otherwise have stretched its
  escape timeline to weeks. CRV likely evicts on its next tick near -1%.
  Timeline audit result: the drain itself HAD fired exactly on schedule
  (14:38, five coins marked unproductive); only the eviction tolerance was
  too tight. Sidecar events (DRAINING/RETIRED) don't appear in the bot-log
  monitor - noted to check both logs when auditing time-bound actions.
- **2026-07-15 17:03** — PUMP (joined via rotation this morning) closed its
  first deal +1.85% in 5.6h. Closed-deal scoreboard: 18 wins, 0 losses.
- **2026-07-15 15:06** (logged 15:50) — Second corridor-brake case: HEI
  latched at −16.5% drawdown (its brake level: 1.5 × its 5.6% wave = 8.4%,
  floored to 12%). Grid has already peeled fills down from 11 to 8, exposure
  $132 → $105. Same "negative %" display quirk as ZBT — each slice actually
  sold above its own cost; the number shown compares against the blended
  average. Two coins braked, both winding down exactly as designed; the
  other 8 slots keep trading normally — this is the "one bad coin can't
  poison the portfolio" behavior working live.
