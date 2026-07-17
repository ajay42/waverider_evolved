# CONTEXT — Wave Rider session state (reload this first)

**Purpose of this file:** full working context for resuming after a context
reset. Read top to bottom, then check DEVLOG.md for anything newer than the
"last updated" stamp below (DEVLOG is newest-first — check its TOP entry,
right after the header, not the bottom). Keep this file UPDATED at every
milestone — it is the session's recovery point.

**Last updated:** 2026-07-17 — RESOURCE POLICY SET (Ajay's order after his
5h usage limit kept exhausting; supersedes the earlier token-lean note):
- **Model policy:** Ajay runs his side at Opus/high-effort by default (his
  own `/model` choice, not something Claude controls). Claude scales
  Sonnet/Fable for its own work (mainly which model it picks when spawning
  subagents), matched to task difficulty. EXCEPTION: anything touching
  capital-safety-critical code — the three governors (corridor brake,
  crash freeze, aggregate exposure), ladder math, lifecycle phase
  transitions, entry/exit gating — gets extra reasoning depth regardless
  of cost. Correctness beats convenience on critical components, always.
- **Heartbeat:** every 8 HOURS, MISSION-CRITICAL-ONLY (not a trade digest):
  (1) both containers up, (2) grep both logs since last check for
  CORRIDOR BRAKE / CRASH FREEZE / Traceback / ERROR, (3) aggregate exposure
  within ceiling. Silent (no chat message, no file write) on a clean check
  — only writes a DEVLOG entry and flags Ajay if something needs
  attention. Never arms a standing log-stream Monitor (that pattern is the
  likely original cause of the usage burn) and never spawns subagents for
  the routine check. Session-only — recreate on session restart at the
  same 8h cadence and scope.
- **Trade notifications:** NO per-trade monitors ever, and no routine
  digest either — the heartbeat above only speaks when something's wrong.
  Ajay checks trade detail himself via status.py / FreqUI when he wants it.
- **Resource dedication:** Ajay's Claude usage is fully allocated to this
  project for now (not a constraint on session/subagent structure). Fresh
  session per work phase still stands — read this file + DEVLOG's top
  entry, not old chat. Big outputs to files, not chat. Batch questions.
  Long compute runs unattended; results reviewed in ONE turn. Scripts are
  standalone — Ajay can run run_stage2.py / status.py / analyzers himself
  at zero Claude cost.
- **Adaptive throttling:** Claude cannot directly read Ajay's 5h usage
  meter. Trigger to downshift: Ajay flags it, or clear proxy signs
  (frequent context compaction, degraded turnaround). Downshift = pause
  launching new heavy sweeps/multi-run backtests and subagent work, stick
  to file/script-based checks and small fixes only, until Ajay confirms
  the limit reset — then resume the queued work at full intensity.
(48h mission effectively concluded; remaining queue in section 5 hands
over to normal-cadence work.)
**Newest capital rule:** 60% ceiling applies to FRESH deployment; parked
capital exempt up to 20% of wallet (inactive during freeze + 6h after);
hard 20% floor untouchable by any code path. Joiners must clear the 2.0
quality floor (empty slot beats mediocre coin).

**Mission scoreboard (hour 32):**
- CRASH TESTS: definitive PASS on repaired data (run 2, 20/20): governed
  deployment ≤7% vs 17-37% ungoverned; zero capitulations; worst window
  −3.33% vs −9.85%; freeze proven (saved ~2pp in LUNA window). Report +
  addendum in Analysis And Reports. Three-layer freeze bug chain + the
  --prepend data-gap lesson documented in DEVLOG (16-July entries).
- SELECTOR: predictive-power PROVEN — decile table monotonic 6.2→37.0
  fwd waves/week, median Spearman 0.806 (report in folder). Scoring math
  has known-answer unit tests in the pre-deploy gate.
- RUNNING NOW (launched ~23:45 UTC): stage-2 sweep, 18 train runs (~10h):
  12 geometry (dev 1/2/3 × vol 1.05/1.10) + 6 of AJAY'S BEST-COINS
  EXPERIMENT (top-5 cohorts; best5_static vs best5_dyn_a k/m=0.4/0.4 vs
  best5_dyn_b 0.6/0.5) on 2022 train windows; validation on 2026 windows
  after via --validate. Log: user_data/stage2_run.log; results:
  backtest_results/stage2/.
- NEW STRATEGY CAPABILITY: dynamic_ladder_enabled — per-coin spacing/TP =
  mult × coin amplitude, clamped [0.8,5]%, set at BO, frozen per deal
  (code default off; used by stage-2B variants). Live config does NOT
  have it on. Per-coin position SIZING deliberately deferred (needs
  P1-2 sizing framework — do not bolt on hastily).
- DEFERRED past mission end (be honest with Ajay): structure refactor
  (flow file + modules — must not touch strategy mid-sweep), two-stage
  ladder, score-scaled sizing, rotation replay, graphs, synthetic MC,
  ablation, selector doctor. Live tally: ~40 closes, ZERO losing full
  closes; ALLO 3 wins since cooldown rejoin; braked coins wind down fine.

---

## 1. What this is

Wave Rider DCA: Ajay's crypto trading strategy. Core purpose (check every
change against this): **get out of bad deals profitably, never let capital
get trapped, waves are the fuel. Capital safety before returns.**
Mechanics: no entry signal (always-in), pre-calculated safety-order ladder,
selective "skim" exits (close best combo of extreme fills), deal lifecycle
(grace → grid → wave-ride → decision) timed in each coin's own wave period,
three safety governors (corridor brake / crash freeze / aggregate ceiling),
amplitude-ranked dynamic coin selection with quality-floor rotation and
slot parking. Everything dry-run (paper) on Binance spot via Freqtrade.

## 2. Where everything lives

```
C:\Users\ajay\Desktop\code by claude\
  CONTEXT.md            <- this file
  DEVLOG.md             <- timestamped mission journal (append-only)
  DESIGN.md ->          freqtrade/DESIGN.md (architecture spec)
  freqtrade/
    docker-compose.yml  <- TWO services: "freqtrade" (bot) + "freqtrade-pairlist" (coin picker)
    CAPITAL_SAFETY.md   <- safety spec (P0-1/P0-2/P1-1 implemented; P1-2 pending)
    LOGIC_FLOW.md       <- ONE-PAGE pseudocode of the whole system; keep updated
    user_data/
      config.json       <- ALL tunables in "wave_rider" section; FreqUI creds in api_server
      config_backtest.json
      strategies/WaveRiderDCA.py   <- the bot (~1,300 lines)
      scripts/pairlist_updater.py  <- the coin picker sidecar
      scripts/{run_matrix,run_tail,analyze_matrix,analyze_tail,monte_carlo,
               build_cohorts,find_regime_windows,test_sidecar}.py
      pairlist.json / pairlist_state.json  <- picker->bot handoff files
      backtest_results/{matrix,tail}/      <- result zips by run name
      cohorts/          <- as-of coin lists per backtest window
      logs/phase_d_decisions.jsonl         <- capitulation decision log
  Analysis And Reports/ <- dated markdown reports (stage-1 matrix + backtest reports)
  Code Backups/         <- 2026-07-15-tier1-governors/, 2026-07-16-pre-parking/,
                           simple-reference-wave-rider/ (the plain-Python original)
  wave_rider_dca/       <- original simple simulator + REGENERATION_PROMPT.md
```

FreqUI: http://localhost:8080 (user "freqtrader", password in config.json).
Docker binary: `"/c/Program Files/Docker/Docker/resources/bin/docker.exe"`
(not on PATH). Bash needs `MSYS_NO_PATHCONV=1` for container paths.

## 3. Live state (as of last update)

- Dry-run since 2026-07-14 14:38 UTC. Closed-deal scoreboard: **19 wins,
  0 losing closes** (excl. penny drain-evictions: U −0.24%, XAUT −0.59%,
  U −0.22%, XAUT −0.19%, INJ −0.04%) + grid partials on braked coins.
- **Parked (winding down, not consuming slots):** ZBT (braked −24%, ~$190),
  HEI (braked −16.5%, ~$105), CRV (draining). List = 13 pairs, 10 fresh.
- Config highlights now live: phase_order "grid,wr" (stage-1 winner),
  run-limit OFF (quality floor 2.0 rotates instead), drain fast-exit 1%,
  parking on (max 3, refill gate 45%), all governors on.
- KNOWN quirk: freqtrade shows per-exit profit% vs blended average, so
  profitable grid slices can display negative. Ledger truth ≠ display.

## 4. Background work in flight

- **Tail safety: run-1 CORRECTED** — data gaps found (no --prepend =
  older ranges silently dropped; BTC missing everywhere + 1-4 cohort
  coins/window). Within-window comparisons stand; absolutes understated;
  freeze untested. Data repaired + verified; freeze signal rewired via
  BTC informative merge (ref_change_24h column in every pair's frame);
  run-1 zips quarantined (tail/run1-datagaps/); slimmed 20-run re-sweep
  READY (run_tail.py, 5 variants). IN PROGRESS at context-save time:
  freeze-engagement diagnostic over 20210514-22 (FZDBG instrumentation in
  strategy — REMOVE after diagnosis); then launch the 20-run sweep;
  then report addendum. NOTE: live bot NOT restarted since informative
  changes — restart + monitor re-arm needed at next deploy anyway.
  Blocked intermittently by permission-service outages; retry Bash.
- **Live monitor**: docker-log follower streaming trade/governor events
  (re-arm after every bot restart! pattern includes CORRIDOR BRAKE,
  CRASH FREEZE, drain_close, phase_d, lifecycle transitions).
- **Heartbeat cron** 41e13bd4 every 2h: drives the mission between events
  (session-only; recreate if session restarted).

## 5. The 48h mission (2026-07-15 15:45 -> 2026-07-17 15:45 UTC)

Mandate: develop/test/evolve/stress-test/audit/backtest/review/plot
autonomously; mission-critical rigor; backups at MAJOR iterations only;
ping Ajay (simple language) only at behavior-changing forks; DEVLOG is the
reporting channel. Plan position: crash-test report next -> Monte Carlo ->
stage-2 walk-forward (incl. lifecycle-length sweep + amplitude-normalized
+ two-stage ladder + conditional grace) -> structure refactor (flow file +
modules; AFTER tail runs finish) -> more unit tests -> graphs ->
synthetic-crash MC -> purpose audit.

## 6. Standing rules and conventions

1. Reports -> "Analysis And Reports/", dated markdown.
2. Snapshot to "Code Backups/<date>-<milestone>/" BEFORE major changes.
3. LOGIC_FLOW.md updated on every flow change (it ships with backups).
4. **No decision-code edit deploys without `python user_data/scripts/test_sidecar.py` passing** (rule born from the 07-15 closes-branch regression).
5. Simple language with Ajay; justify against the purpose; validate > build.
6. Every terminal coin state needs its own entry-gate block (lesson from
   the U/XAUT reopen bug).
7. Check BOTH containers' logs when auditing time-bound actions (drain
   events log in the SIDECAR, trades in the BOT).
8. Timestamps: bot/sidecar log UTC; Ajay is UTC+5:30.

## 7. Decision history in one breath

Stage-1 matrix (30 runs): life_grid_first wins consistency; grace positive
except chop×wave; wave cohort = bear/chop edge, majors = bull edge;
recycling needs the lifecycle. Tier-1 governors implemented per
CAPITAL_SAFETY.md after Ajay's "go". Run-limit removed for quality-floor
rotation (Ajay). Parking added (Ajay's idea + safety package). Phase-D
−15% is a capitulation floor, NOT a stop (never tune loss% for safety —
tune wave-age deadlines). 60% ceiling = crash budget; real idle-capital
fix is P1-2 %-wallet sizing (queued). Magenta chart lines = all orders
with an armed TP in any phase. Stepped historical chart lines: QUEUED.

## 8. Resume checklist after a context reset

1. Read this file, then DEVLOG.md from the TOP (right after the header —
   DEVLOG is newest-first, new entries are inserted there, not appended
   at the bottom).
2. `docker ps` — expect freqtrade + freqtrade-pairlist up; tail-run
   containers may exist while the sweep runs. If the daemon isn't up yet
   (e.g. right after a Windows reboot), wait ~30-60s and recheck before
   assuming a real problem — Docker Desktop takes a moment to start and
   the containers rejoin on their own via the compose restart policy.
3. Check tail sweep: count zips in backtest_results/tail/ (target 28);
   log at user_data/tail_run.log.
4. No standing log monitor to re-arm by design — the 8h heartbeat (below)
   covers governor trips / errors on its own schedule instead.
5. Recreate the 8h mission-critical-only heartbeat cron if the session
   restarted (see the top of this file for scope).
6. Memory files (auto-loaded) hold durable project facts; this file holds
   operational state. Trust newer over older; verify anything critical
   against the DB/logs before acting.
