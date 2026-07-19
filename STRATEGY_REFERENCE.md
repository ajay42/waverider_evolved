# WaveRider — Strategy Reference Card

A months-later, plain-language reference for the person running this strategy.
What it is, how each piece works, the numbers, what to expect, and how to
operate it. For deep architecture see `freqtrade/DESIGN.md`; for the one-page
flow see `freqtrade/LOGIC_FLOW.md`; for the evidence see `Analysis And Reports/`.

---

## 1. What this strategy is (in one breath)

> Every trader eventually gets stuck in a bad deal. WaveRider deliberately
> starts "stuck" with a tiny base order, then uses price **waves** to reduce
> exposure and escape profitably. Volatility is the fuel. It sacrifices trend
> profit for account safety. **The enemy is not drawdown — it's trapped
> ("zombie") capital.**

**What it IS:** a capital-preservation / drawdown-control engine. Its edge is
surviving crashes and never trapping money.
**What it is NOT:** a profit machine. In calm/chop markets it grinds near
break-even. Judge it by drawdown control, not returns.

---

## 2. The core mechanic (how one deal works)

```
BASE ORDER      tiny buy opens the deal immediately (no entry signal - always in)
   |
SAFETY ORDERS   pre-calculated ladder of larger buys below, filled as price falls
   |            (rungs & sizes fixed at deal open; per-coin USD cap on every buy)
   |
SKIM            when price waves back up, close the best COMBO of extreme fills
   |            (oldest + newest, up to 3) for profit - not the whole position
   |
RECYCLE         after a partial skim, reopen ONE order at the deepest closed rung
   |            to catch the next wave
   v
repeat until the deal is fully closed (all fills skimmed off)
```

Small base order is deliberate: it keeps the blended average close to price so
small waves can skim it profitably.

---

## 3. The deal lifecycle (phases by the coin's own wave period)

A deal ages through phases measured in that coin's **wave period** (~13–17h),
not clock hours. Phases change *exit* behaviour only.

```
GRACE     waves 0-3    plain DCA: one TP closes the whole position (blended avg +2%)
GRID      waves 3-6    sell-only: peel each fill at its own cost +0.5%, deepest first
WAVE-RIDE waves 6-12   the classic combo-skim + recycle mechanic
DECISION  waves 12+    no buys; at the deadline: close if loss small, else extend once
```
(Live phase order is "grid,wr" — the stage-1 matrix winner.)

---

## 4. The safety governors (the reason it's safe)

| Governor | Triggers when | Does |
|---|---|---|
| **Corridor brake** | a coin falls further than its own waves explain (or exposure trips) | latches that deal to sell-only forever |
| **Crash freeze** | BTC drops >5% / 24h (hysteresis) | all deals sell-only, no new buys |
| **Aggregate ceiling** | fresh deployment would exceed 60% of wallet | blocks new deals |
| **5-day age cap** | any deal open ≥ 5 days | force-closes it (loss accepted) — no deal traps capital past 5 days |

**Proven:** on real crashes, governors cut peak deployment from 17–37% to ~6–7%;
on a synthetic 80% grind, loss −19.8% → −4.3%. None is a price stop-loss — they
free capital, they don't chase price.

---

## 5. Coin selection (the edge)

- **Score = wave amplitude × (1 − trendiness)** — rewards choppy, wavy coins;
  punishes one-way movers (pumps AND crashes).
- **Filters:** 24h + median-daily volume floors (pump-and-dump gate), spread
  <0.1%, listing age ≥14d.
- **Rotation:** coins drain out when their score drops below the quality floor;
  joiners must clear the same floor (empty slot beats a mediocre coin).
- **Proven predictive** (decile-monotonic, Spearman ~0.8) — this is the biggest
  single edge; prioritise it.

---

## 6. The key numbers (current live config)

| Knob | Value | Meaning |
|---|---|---|
| base order | $10 | tiny admission to "stuck" |
| SO spacing / volume | 2% / ×1.1 | ladder geometry |
| per-coin cap | $1000 | hard worst-case per coin |
| max coins | 10 | worst-case = 10 × cap, known up front |
| aggregate ceiling | 60% | of wallet, fresh deployment |
| max deal age | 5 days | hard trap backstop |
| quality floor | 2.0 | selection/rotation threshold |

*An optimized "candidate" config exists (more conservative: brake 1.5→2.8,
spacing 2→1.4, dynamic per-coin ladder ON). It's an inert proposal — review its
diff before adopting. Deploy current-live first.*

---

## 7. What to expect (set your expectations here)

- **Most exits are small wins** (grace/skim). Win rate is high (~75–95%).
- **Some exits are small managed losses** (drain / age-cap / Phase-D). These are
  the safety system *freeing stuck capital* — a design feature, not a failure.
- **Net result in calm markets:** roughly break-even to slightly positive.
- **Net result in crashes:** far smaller losses than buy-and-hold or plain DCA.
- **It will NOT** produce big returns in a bull run — it takes profit early.

---

## 8. How to operate it (the operator's guide)

**Weekly:** run `python user_data/scripts/weekly_summary.py` → read the digest.
Watch **real losses** (not managed exits) and open exposure vs the ceiling.

**Monitor for:** crash-freeze engaging (expected in dumps), container down, any
traceback. FreqUI (via SSH tunnel on cloud) shows live deals + the chart lines
(yellow = next buy, cyan = average, green = TP trigger, magenta = orders it will
close).

**When to worry:** repeated *real* losses (from grace/skim paths) sharing deep
drawdown (>15%) or old age (>12 waves) → the selector may be picking trendy, not
wavy, coins. That's the lever to check first — selection, not the exit rules.

**When NOT to worry:** age-cap and Phase-D closes at small losses. Braked coins
winding down. Freeze during a market dump. All by design.

**Sizing (going live):** start small enough that the worst case (coins × per-coin
cap) is a tuition fee. Scale only after live fills match paper. Keys must be
**spot-only, withdrawals OFF, IP-locked** (see `freqtrade/CLOUD_DEPLOYMENT.md`).

**Never live-tune on recent results.** Improvements come as reviewed candidate
configs from the offline relearn cycle — never auto-applied.

---

## 9. Quick reference (files & commands)

```
Run the bot (local):     docker compose up -d          (in freqtrade/)
Weekly summary:          python user_data/scripts/weekly_summary.py
Refresh model+candidate: python user_data/scripts/relearn_cycle.py
Backtest a crash:        python user_data/scripts/run_tail.py
Sidecar tests (gate):    python user_data/scripts/test_sidecar.py   # MUST pass before any deploy

Strategy code:  freqtrade/user_data/strategies/WaveRiderDCA.py
Coin picker:    freqtrade/user_data/scripts/pairlist_updater.py
Config (secrets, gitignored): freqtrade/user_data/config.json
```

**The one rule that governs everything:** *escape bad deals profitably, never
trap capital, capital safety before returns.* Check every change against it.
