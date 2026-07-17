# Wave Rider DCA — Freqtrade deployment

Dry-run deployment of the Wave Rider DCA strategy (spec:
`../wave_rider_dca/REGENERATION_PROMPT.md`). FreqUI: http://localhost:8080
(credentials in `user_data/config.json` → `api_server`).

## Services (docker-compose.yml)

| service | what it does |
|---|---|
| `freqtrade` | the trading bot + FreqUI on port 8080 |
| `pairlist-updater` | ranks Binance USDT markets by wave amplitude (avg 4h high-low swing %), retires coins that finished their runs, refills `user_data/pairlist.json` |

Start/stop: `docker compose up -d` / `docker compose down` (in this folder).

## Tuning — no code edits needed

All strategy knobs live in `user_data/config.json` → `"wave_rider"`:

- `max_deal_restarts` — full deals ("runs") a coin gets per stint on the list
- `take_profit_perc`, `safety_order_price_deviation_perc` — skim TP and ladder spacing (%)
- `base_order_size_usd`, `safety_order_size_usd`, `safety_order_volume_scale`,
  `safety_order_price_step_scale`, `max_safety_orders` — ladder shape
- `max_exposure_per_coin_usd` — hard per-coin capital cap
- `combo_selection` — `"outer_pair"` (spec: always close oldest+newest) or
  `"best_combo"` (close whichever extreme-order combo has the lowest TP;
  greedy, capped at `combo_max_orders` fills, oldest fill always included)
- `recycle_last_so` — after a partial skim closes 2–3 fills, reopen exactly
  ONE order at the deepest closed rung's pre-calculated price (cap-gated;
  keeps deals alive longer but harvests every wave)
- `max_coins` — active list size (keep `pairlists[0].number_assets` in sync)
- `pairlist_refresh_seconds`, `rejoin_cooldown_hours`,
  `liquidity_universe_size` — sidecar behaviour
- `amplitude_interval`, `amplitude_lookback_candles` — the wave-amplitude
  score: average high-low swing of the last N candles at that interval
  (defaults: 42 × 4h = one week)
- `min_quote_volume_24h_usd`, `min_median_daily_volume_usd` — liquidity
  floors; the median-daily one is the pump-and-dump gate (a spike inflates
  one day's volume, not the week's median)
- `max_stint_hours`, `min_profit_per_day_usd`, `profit_grace_hours` —
  rotation: a coin past its stint limit (or earning under the floor, if
  enabled) is marked DRAINING: recycling stops, no new deals start, skims
  wind it down, and it retires (slot freed) the moment it goes flat

### Selector filters — each individually toggleable (for backtest A/Bs)

- `use_choppiness_filter` + `max_trendiness` — drop coins whose weekly move
  is mostly one-way (trendiness = |net move| ÷ path length; pumps AND
  crashes score ~1, pure waves ~0)
- `choppiness_weighted_ranking` — score by amplitude × (1 − trendiness)
  instead of raw amplitude
- `use_spread_filter` + `max_spread_perc` — skip thin books whose bid-ask
  spread would eat the take-profit
- `use_age_filter` + `min_listing_age_days` — skip coins still in
  post-listing price discovery
- `regime_brake_enabled` + `regime_brake_btc_drop_perc` +
  `regime_reference_pair` — strategy-side: pause NEW base orders while BTC
  is down more than the threshold over 24h (existing deals keep managing)

### Deal lifecycle (see DESIGN.md — phases change exit behaviour only)

- `lifecycle_enabled` — master switch; off = pure Wave Rider all the way
- `phase_order` — `"wr,grid"`, `"grid,wr"`, or `"regime"` (per-deal pick at
  grace failure: healthy market → WR first, crash → grid first)
- `grace_waves` / `winddown_waves` / `decision_waves` / `decision_wait_waves`
  — phase boundaries in the coin's OWN wave periods (sidecar measures each
  coin's wave period; `wave_period_fallback_hours` when missing)
- `grid_margin_perc` — sell-only grid: each fill exits at its own price + this
- `phase_d_loss_threshold_perc`, `phase_d_min_wave_score`,
  `phase_d_max_extensions` — the mechanical capitulation rules; every
  decision is logged to `user_data/logs/phase_d_decisions.jsonl`
- `drain_fast_exit_max_loss_perc` — a DRAINING coin at/near breakeven
  (loss ≤ this %) closes immediately (`drain_close`) instead of waiting
  out the lifecycle; negative disables. A `phase_d_close` also hard-blocks
  any new deal for the rest of that coin's stint (strategy-side gate).

Workflow: edit the value → click **Reload Config** in FreqUI (bot picks it up
via `bot_start`; the sidecar re-reads config every cycle automatically).

## How the dynamic coin list works

1. Sidecar scores the top-N most liquid USDT markets by wave amplitude —
   the average high-low swing of recent 4h candles as % of their midpoint
   (liquidity is only the filter; waves are the score, because a skim needs
   the price to travel take-profit + fees). Coins younger than the lookback
   rank last, keeping fresh post-listing pumps out until they have history.
2. A coin retires once it has `max_deal_restarts` closed deals **since it
   joined** the list and holds no open trade — its slot is refilled by the
   highest-delta candidate not on cooldown (`rejoin_cooldown_hours`).
3. `pairlist.json` feeds the bot (RemotePairList, re-read every 5 min);
   `pairlist_state.json` records join/retire times — the strategy counts a
   returning coin's runs from its latest join (fresh allowance per stint).

## Files

- `user_data/strategies/WaveRiderDCA.py` — deployed strategy (spec port)
- `user_data/strategies_backup/WaveRiderDCA_primed_group.py` — earlier
  "primed group" variant (ftwr3 lineage), not deployed
- `user_data/scripts/pairlist_updater.py` — the sidecar
- `user_data/tradesv3.sqlite.bak-*` — archived dry-run databases
  (primed-variant run; 0.3%-threshold demo run)

## Gotchas learned the hard way

- `api_server.listen_ip_address` must be `0.0.0.0` in docker (host access is
  still restricted by the `127.0.0.1:8080:8080` port mapping).
- Market orders require `entry_pricing`/`exit_pricing` `price_side: "other"`.
- RemotePairList `file://` URLs resolve *relative to the working directory*
  after the scheme — an absolute container path needs FOUR slashes:
  `file:////freqtrade/user_data/pairlist.json`.
