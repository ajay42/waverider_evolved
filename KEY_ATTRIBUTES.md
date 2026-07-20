# WaveRider — Key Attributes & User Suggestions

## Key attributes (what this system is)

- **Identity:** a capital-preservation trading system, not a profit engine.
  Edge = surviving crashes + never trapping capital. Near break-even in calm
  markets by design.
- **Always-in:** no entry signal — a fresh coin opens a tiny base order
  immediately; the strategy assumes every trade starts "stuck" and works out.
- **Pre-calculated everything:** safety-order ladder prices/sizes fixed at deal
  open; no ad-hoc orders ever.
- **Skim exits:** closes the best combo of extreme fills (oldest + newest, ≤3)
  on each wave — partial profit-taking, not full-position recovery waits.
- **Wave-normalized lifecycle:** deal phases (grace → grid → wave-ride →
  decision) timed in each coin's own measured wave period, not clock hours.
- **Four safety governors, all proven in tests:**
  - corridor brake (coin fell beyond its own waves → sell-only, latched)
  - crash freeze (BTC −5%/24h → everything sell-only, no new buys)
  - aggregate ceiling (fresh deployment ≤ 60% of wallet)
  - **5-day age cap** (no deal lives past 5 days — force-closed, loss accepted)
- **Data-driven coin selection:** wave-amplitude × choppiness scoring with
  volume/spread/age filters and a quality floor; proven predictive
  (Spearman ~0.8). This is the biggest single edge.
- **Offline-only self-learning:** optimizer proposals are inert files that must
  pass an adversarial review gate; the bot never tunes itself live. (The gate
  already rejected its first candidate — it deployed 2× capital in crashes.)
- **Current sizing (500 USDT test account, 2-month evaluation):**
  - wallet 500 USDT · per-coin cap $50 · 10 concurrent coins max
  - orders $5 (base + safety), ladder covers ~12% dip, then the brake owns it
  - worst case is always known: 10 × $50 = the whole wallet, ceiling-limited
    to $300 fresh deployment

## Suggestions to the user

- **Judge it on drawdown control and clean exits, not returns.** Flat-to-small-
  positive months with small controlled crash losses = the system working.
- **Small losses tagged `age_cap_close` / `phase_d_close` / `drain_close` are
  features** — capital being freed from dead deals. Don't tune them away.
- **Run `weekly_summary.py` weekly** — it separates real losses (watch these)
  from managed capital-freeing exits (expected). Act only on real losses.
- **If real losses cluster:** check the coin selector first (trendy coins
  sneaking past the wave filters), not the exit rules.
- **Never live-tune on recent results.** Changes come only as reviewed
  candidate configs through the relearn gate.
- **Going live later:** API keys spot-only, withdrawals OFF, IP-locked; start
  at a size where the worst case is a tuition fee; scale only after live fills
  match paper for weeks.
- **Keep the repo private** — it contains the full edge.
- **Kill-switch:** FreqUI force-exit + the crash freeze give you manual
  stop-and-drain; practice once in dry-run.
- **Expectations by market:** bull → it takes profit early and underperforms
  holding; chop → its best habitat (waves = fuel); crash → its reason to exist
  (losses several times smaller than ungoverned DCA).
