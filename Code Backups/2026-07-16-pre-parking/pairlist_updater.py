"""
Pairlist updater - the sidecar that keeps the bot's coin list dynamic.

What it does, every refresh cycle:

1. RANK: pull all Binance USDT spot markets, keep the most liquid ones
   (top N by 24h quote volume - liquidity is a FILTER, not the score),
   and rank them by WAVE AMPLITUDE - the average high-low swing of
   recent 4h candles as a % of their midpoint. The strategy earns on
   waves >= take-profit + fees, so the priority list measures exactly
   that: which liquid coins are actually producing waves big enough to
   skim, regardless of whether their volume is rising or falling.

2. RETIRE: read the bot's trade database. An active coin retires when it
   has completed its preset number of runs (closed deals SINCE IT JOINED
   the list - see pairlist_state.json) and has no open trade left.

3. REFILL: top the active list back up to `max_coins` with the
   highest-delta candidates that aren't already active and aren't in the
   rejoin cooldown window.

4. WRITE: atomically write
     - pairlist.json        -> read by freqtrade's RemotePairList
     - pairlist_state.json  -> when each coin joined / retired; the
                               strategy's restart gate reads join times
                               so a returning coin gets a fresh allowance.

All knobs live in the "wave_rider" section of config.json, so tuning =
edit config.json + click "Reload Config" in FreqUI (the sidecar re-reads
the config every cycle; no restart needed).

Run modes:
    python3 pairlist_updater.py          # loop forever (docker service)
    python3 pairlist_updater.py --once   # single pass (seeding/testing)
"""

import json
import shutil
import sqlite3
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Windows consoles default to a legacy codepage; some market names contain
# characters it can't encode. Force UTF-8 so logging never kills a cycle.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# scripts/ lives inside user_data/, so this works on the host and in docker.
USER_DATA = Path(__file__).resolve().parents[1]
PAIRLIST_FILE = USER_DATA / "pairlist.json"
STATE_FILE = USER_DATA / "pairlist_state.json"
DB_FILE = USER_DATA / "tradesv3.sqlite"
TMP_DIR = USER_DATA / "tmp"

BINANCE = "https://api.binance.com"

# Bases that are themselves dollar-pegged (nothing to ride) and leveraged
# token patterns. The config-level pair_blacklist also applies downstream.
STABLE_BASES = {"USDC", "TUSD", "FDUSD", "BUSD", "DAI", "EUR", "EURI", "USDP",
                "AEUR", "XUSD", "USD1", "RLUSD", "USDE", "USDS", "USDD", "PYUSD"}


def log(msg: str) -> None:
    print(f"{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} [pairlist] {msg}", flush=True)


def load_settings() -> dict:
    config = json.loads((USER_DATA / "config.json").read_text())
    wr = config.get("wave_rider", {})
    return {
        "max_coins": int(wr.get("max_coins", 10)),
        "max_deal_restarts": int(wr.get("max_deal_restarts", 3)),
        "refresh_seconds": int(wr.get("pairlist_refresh_seconds", 900)),
        "rejoin_cooldown_hours": float(wr.get("rejoin_cooldown_hours", 24)),
        "liquidity_universe_size": int(wr.get("liquidity_universe_size", 50)),
        "amplitude_interval": str(wr.get("amplitude_interval", "4h")),
        "amplitude_lookback_candles": int(wr.get("amplitude_lookback_candles", 42)),
        # Volume floors: pump-and-dump coins show huge volume DURING the pump
        # but it evaporates after. The 24h floor guarantees liquidity right
        # now; the median-daily floor (over the amplitude lookback window)
        # guarantees it was liquid all week, not just during one spike.
        "min_quote_volume_24h_usd": float(wr.get("min_quote_volume_24h_usd", 10_000_000)),
        "min_median_daily_volume_usd": float(wr.get("min_median_daily_volume_usd", 5_000_000)),
        # Rotation: a coin whose stint exceeds max_stint_hours (or, if the
        # profit rule is enabled, earns below min_profit_per_day_usd after a
        # grace period) is marked DRAINING - the strategy stops recycling it,
        # skims wind the deal down, and it retires the moment it goes flat.
        "max_stint_hours": float(wr.get("max_stint_hours", 72)),
        # Quality floor: an active coin whose CURRENT wave score falls
        # below this drains out - rotation is quality-driven, not
        # counter-driven. 0 disables.
        "min_active_wave_score": float(wr.get("min_active_wave_score", 0)),
        "min_profit_per_day_usd": float(wr.get("min_profit_per_day_usd", 0)),
        "profit_grace_hours": float(wr.get("profit_grace_hours", 24)),
        # Choppiness: trendiness = |net move| / path length over the lookback.
        # ~1 = one-way trend (pump-and-dump profile), ~0 = pure waves. The
        # filter drops trendy coins; weighted ranking scores by
        # amplitude * (1 - trendiness) so wavier coins outrank trendier ones.
        "use_choppiness_filter": bool(wr.get("use_choppiness_filter", False)),
        "max_trendiness": float(wr.get("max_trendiness", 0.4)),
        "choppiness_weighted_ranking": bool(wr.get("choppiness_weighted_ranking", False)),
        # Spread: thin books eat the TP. One bookTicker call covers everything.
        "use_spread_filter": bool(wr.get("use_spread_filter", False)),
        "max_spread_perc": float(wr.get("max_spread_perc", 0.1)),
        # Age: coins younger than this are still in post-listing discovery.
        "use_age_filter": bool(wr.get("use_age_filter", False)),
        "min_listing_age_days": int(wr.get("min_listing_age_days", 14)),
    }


def http_json(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "wave-rider-pairlist/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


# ------------------------- step 1: ranking -------------------------

def tradable_usdt_pairs() -> dict:
    """symbol -> 'BASE/USDT' for every live Binance USDT spot market."""
    info = http_json(f"{BINANCE}/api/v3/exchangeInfo?permissions=SPOT")
    pairs = {}
    for s in info["symbols"]:
        if s.get("status") != "TRADING" or s.get("quoteAsset") != "USDT":
            continue
        base = s["baseAsset"]
        if base in STABLE_BASES:
            continue
        if not s["symbol"].isascii():
            continue  # novelty listings with unicode names break URL fetches
        # Legacy leveraged-token names ended in UP/DOWN/BULL/BEAR. Match by
        # suffix, with real coins that happen to share a suffix whitelisted.
        if base.endswith(("UP", "DOWN", "BULL", "BEAR")) and base not in ("JUP", "PUMP"):
            continue
        pairs[s["symbol"]] = f"{base}/USDT"
    return pairs


CANDLES_PER_DAY = {"1h": 24, "2h": 12, "4h": 6, "6h": 4, "8h": 3, "12h": 2, "1d": 1}


def score_symbol(symbol: str, settings: dict, end_ms: int = None) -> tuple:
    """
    Returns (wave_amplitude_pct, median_daily_quote_volume, trendiness,
    wave_period_hours) from one klines fetch. Defaults: 4h candles, 42 of
    them (= one week).

    Wave period = how long this coin's typical down-and-up cycle takes,
    estimated from direction changes in the close series (two direction
    changes = one full wave). The strategy uses it to express deal-lifecycle
    boundaries in THIS coin's rhythm instead of clock hours.

    Trendiness = |net close-to-close move| / total path length travelled.
    ~1 means price went one way (a pump or a crash - big amplitude, no
    exploitable waves); ~0 means price oscillated a lot but went nowhere,
    which is exactly the profile the skim machinery monetises.

    Wave amplitude = average high-low swing as a % of each candle's midpoint.
    This is the quantity the strategy actually monetises: a skim needs the
    price to travel take_profit_perc (+fees) from the combo average, so
    coins whose typical 4h wave is largest give the most skim opportunities.
    A coin too young to have the full lookback is ranked last, which also
    keeps brand-new post-listing pumps out until they have real wave history.

    Median daily quote volume (same candles, no extra API call) backs the
    min_median_daily_volume_usd floor: a pump-and-dump's volume exists only
    during the spike, so its MEDIAN day is thin even when its 24h number
    looks huge.
    """
    interval = settings["amplitude_interval"]
    lookback = settings["amplitude_lookback_candles"]
    url = f"{BINANCE}/api/v3/klines?symbol={symbol}&interval={interval}&limit={lookback + 1}"
    if end_ms:
        url += f"&endTime={end_ms}"  # as-of scoring for backtest cohorts
    klines = http_json(url)
    complete = klines[:-1]  # drop the still-forming candle
    per_day = CANDLES_PER_DAY.get(interval, 6)
    interval_hours = 24.0 / per_day
    if len(complete) < lookback:
        # not enough history: rank last, max trendy, one-candle wave period
        return -999.0, 0.0, 1.0, interval_hours

    swings = []
    for k in complete:
        high, low = float(k[2]), float(k[3])
        mid = (high + low) / 2
        if mid > 0:
            swings.append((high - low) / mid)
    if not swings:
        return -999.0, 0.0, 1.0, interval_hours
    amplitude = 100.0 * sum(swings) / len(swings)

    quote_vols = [float(k[7]) for k in complete]
    daily = [sum(quote_vols[i:i + per_day])
             for i in range(0, len(quote_vols) - per_day + 1, per_day)]
    daily.sort()
    median_daily = daily[len(daily) // 2] if daily else 0.0

    closes = [float(k[4]) for k in complete]
    path = sum(abs(closes[i] - closes[i - 1]) for i in range(1, len(closes)))
    trendiness = abs(closes[-1] - closes[0]) / path if path > 0 else 1.0

    # Direction changes in the close series; a full wave (down+up) is two.
    direction_changes = 0
    prev_sign = 0
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        sign = 1 if diff > 0 else (-1 if diff < 0 else 0)
        if sign != 0 and prev_sign != 0 and sign != prev_sign:
            direction_changes += 1
        if sign != 0:
            prev_sign = sign
    total_hours = len(complete) * interval_hours
    waves = max(direction_changes / 2.0, 1.0)
    wave_period_hours = min(max(total_hours / waves, interval_hours), total_hours)

    return amplitude, median_daily, trendiness, wave_period_hours


def spread_map() -> dict:
    """symbol -> current bid-ask spread in %, one API call for everything."""
    out = {}
    for t in http_json(f"{BINANCE}/api/v3/ticker/bookTicker"):
        try:
            bid, ask = float(t["bidPrice"]), float(t["askPrice"])
        except (KeyError, ValueError):
            continue
        mid = (bid + ask) / 2
        if mid > 0 and bid > 0:
            out[t["symbol"]] = 100.0 * (ask - bid) / mid
    return out


# A coin that has passed the age check stays passed (age only grows), so the
# daily-klines call happens at most once per symbol per process lifetime.
_age_cache: set = set()


def old_enough(symbol: str, min_days: int) -> bool:
    key = f"{symbol}:{min_days}"
    if key in _age_cache:
        return True
    klines = http_json(f"{BINANCE}/api/v3/klines?symbol={symbol}&interval=1d&limit={min_days + 1}")
    ok = len(klines) >= min_days + 1
    if ok:
        _age_cache.add(key)
    return ok


def ranked_candidates(settings: dict) -> list:
    """
    Liquid universe ordered by score (largest first). Every gate below is
    individually toggleable from config.json - handy for backtesting the
    selector with different filter combinations:
      1. hard floor on 24h quote volume (liquid RIGHT NOW) - always on,
      2. top-N by 24h quote volume (relative filter) - always on,
      3. hard floor on the week's MEDIAN daily volume (was liquid all week;
         a pump inflates one day's volume, not the median) - always on,
      4. spread filter (thin books eat the take-profit) - toggle,
      5. choppiness filter (drop one-way trenders: pumps AND crashes) - toggle,
      6. listing-age minimum (skip post-listing price discovery) - toggle.
    Score = wave amplitude, or amplitude * (1 - trendiness) when
    choppiness_weighted_ranking is on, so wavier coins outrank trendier ones.
    """
    pairs = tradable_usdt_pairs()
    tickers = http_json(f"{BINANCE}/api/v3/ticker/24hr")
    liquid = sorted(
        (t for t in tickers
         if t["symbol"] in pairs
         and float(t["quoteVolume"]) >= settings["min_quote_volume_24h_usd"]),
        key=lambda t: float(t["quoteVolume"]),
        reverse=True,
    )[: settings["liquidity_universe_size"]]

    spreads = spread_map() if settings["use_spread_filter"] else {}

    scored = []
    for t in liquid:
        symbol = t["symbol"]

        if settings["use_spread_filter"] and \
                spreads.get(symbol, 999.0) > settings["max_spread_perc"]:
            continue

        try:
            amplitude, median_daily, trendiness, _period = score_symbol(symbol, settings)
        except Exception as exc:  # one bad symbol must not kill the cycle
            log(f"score_symbol failed for {symbol}: {exc}")
            continue
        time.sleep(0.15)  # stay far below Binance rate limits

        if median_daily < settings["min_median_daily_volume_usd"]:
            continue
        if settings["use_choppiness_filter"] and trendiness > settings["max_trendiness"]:
            continue

        # Age check last: it costs an extra API call, so only survivors pay it.
        if settings["use_age_filter"]:
            try:
                if not old_enough(symbol, settings["min_listing_age_days"]):
                    continue
                time.sleep(0.15)
            except Exception as exc:
                log(f"age check failed for {symbol}: {exc}")
                continue

        score = amplitude * (1 - trendiness) \
            if settings["choppiness_weighted_ranking"] else amplitude
        scored.append((score, pairs[symbol]))

    scored.sort(reverse=True)
    return [(pair, score) for score, pair in scored]


# ------------------------- step 2: retirement -------------------------

def read_deal_counts() -> dict:
    """
    pair -> {"open": n, "closed_since": {pair: [close_dates...]}} from a
    COPY of the bot's database (never touch the live file directly).
    """
    if not DB_FILE.exists():
        return {}
    TMP_DIR.mkdir(exist_ok=True)
    db_copy = TMP_DIR / "trades_copy.sqlite"
    shutil.copy(DB_FILE, db_copy)
    wal = DB_FILE.with_name(DB_FILE.name + "-wal")
    if wal.exists():
        shutil.copy(wal, db_copy.with_name(db_copy.name + "-wal"))

    con = sqlite3.connect(db_copy)
    con.row_factory = sqlite3.Row
    result = {}
    for r in con.execute(
        "SELECT pair, is_open, close_date, close_profit_abs, exit_reason FROM trades"
    ):
        entry = result.setdefault(r["pair"], {"open": 0, "closes": []})
        if r["is_open"]:
            entry["open"] += 1
        elif r["close_date"]:
            entry["closes"].append(
                (r["close_date"], r["close_profit_abs"] or 0.0, r["exit_reason"] or ""))
    con.close()
    return result


def _closes_since(deals: dict, pair: str, joined_iso: str) -> list:
    """(close_date, profit_abs) of every deal closed since the pair joined."""
    entry = deals.get(pair)
    if not entry:
        return []
    joined = datetime.fromisoformat(joined_iso)
    out = []
    for close_date, profit, exit_reason in entry["closes"]:
        closed = datetime.fromisoformat(close_date.replace(" ", "T"))
        if closed.tzinfo is None:
            closed = closed.replace(tzinfo=timezone.utc)
        if closed >= joined:
            out.append((closed, profit, exit_reason))
    return out


def closed_runs_since(deals: dict, pair: str, joined_iso: str) -> int:
    return len(_closes_since(deals, pair, joined_iso))


def realized_profit_since(deals: dict, pair: str, joined_iso: str) -> float:
    return sum(profit for _, profit, _ in _closes_since(deals, pair, joined_iso))


def capitulated_since(deals: dict, pair: str, joined_iso: str) -> bool:
    """Did a Phase D capitulation close happen this stint? A broken thesis
    must rotate the coin out - it must not restart a fresh deal."""
    return any(reason == "phase_d_close"
               for _, _, reason in _closes_since(deals, pair, joined_iso))


# ------------------------- steps 3+4: refill and write -------------------------

def atomic_write(path: Path, payload: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2))
    tmp.replace(path)


def run_cycle() -> None:
    settings = load_settings()
    now = datetime.now(timezone.utc)

    state = {"active": {}, "retired": {}, "draining": {}}
    if STATE_FILE.exists():
        state = json.loads(STATE_FILE.read_text())
        for key in ("active", "retired", "draining"):
            state.setdefault(key, {})

    deals = read_deal_counts()

    # --- rotation: mark stale/unproductive coins as DRAINING ---
    # A draining coin stops recycling (the strategy reads this flag), so its
    # skims wind the deal down monotonically; it retires the moment it's flat.
    for pair, joined_iso in state["active"].items():
        if pair in state["draining"]:
            continue
        stint_hours = (now - datetime.fromisoformat(joined_iso)).total_seconds() / 3600
        reason = None
        if capitulated_since(deals, pair, joined_iso):
            reason = "phase D capitulation - thesis broken, rotate out"
        elif stint_hours > settings["max_stint_hours"]:
            reason = f"stint {stint_hours:.0f}h > {settings['max_stint_hours']:.0f}h"
        elif (settings["min_active_wave_score"] > 0
              and state.get("scores", {}).get(pair) is not None
              and state["scores"][pair] < settings["min_active_wave_score"]):
            reason = (f"wave score {state['scores'][pair]:.2f} < "
                      f"{settings['min_active_wave_score']} quality floor")
        elif (settings["min_profit_per_day_usd"] > 0
              and stint_hours > settings["profit_grace_hours"]):
            realized = realized_profit_since(deals, pair, joined_iso)
            rate = realized / (stint_hours / 24)
            if rate < settings["min_profit_per_day_usd"]:
                reason = (f"earning {rate:+.2f} USD/day < "
                          f"{settings['min_profit_per_day_usd']} floor")
        if reason:
            state["draining"][pair] = now.isoformat()
            log(f"DRAINING {pair}: {reason} -> recycling off, retires when flat")

    # --- retire finished coins: (runs done OR draining) AND flat ---
    still_active = {}
    for pair, joined_iso in state["active"].items():
        runs = closed_runs_since(deals, pair, joined_iso)
        has_open = deals.get(pair, {}).get("open", 0) > 0
        done = runs >= settings["max_deal_restarts"] or pair in state["draining"]
        if done and not has_open:
            state["retired"][pair] = now.isoformat()
            state["draining"].pop(pair, None)
            log(f"RETIRED {pair}: {runs}/{settings['max_deal_restarts']} runs, flat -> slot freed")
        else:
            still_active[pair] = joined_iso
    state["active"] = still_active

    # --- refill from the volume-delta ranking ---
    free_slots = settings["max_coins"] - len(state["active"])
    if free_slots > 0:
        cooldown = timedelta(hours=settings["rejoin_cooldown_hours"])
        candidates = ranked_candidates(settings)
        for pair, delta in candidates:
            if free_slots == 0:
                break
            if pair in state["active"]:
                continue
            retired_iso = state["retired"].get(pair)
            if retired_iso and now - datetime.fromisoformat(retired_iso) < cooldown:
                continue  # let it cool off before a fresh allowance
            state["active"][pair] = now.isoformat()
            state["retired"].pop(pair, None)
            free_slots -= 1
            log(f"JOINED {pair} (wave score {delta:.2f})")

    # --- telemetry for the strategy's lifecycle machinery ---
    # Current wave score (same formula as the ranking) and wave period for
    # every active pair. The strategy reads these to (a) express phase
    # boundaries in the coin's own wave rhythm and (b) drive the Phase D
    # "is this still a wave coin?" rule mechanically.
    scores, periods, amplitudes = {}, {}, {}
    for pair in state["active"]:
        symbol = pair.replace("/", "")
        try:
            amplitude, _vol, trendiness, period = score_symbol(symbol, settings)
        except Exception as exc:
            log(f"telemetry failed for {symbol}: {exc}")
            continue
        scores[pair] = round(amplitude * (1 - trendiness), 4) \
            if settings["choppiness_weighted_ranking"] else round(amplitude, 4)
        periods[pair] = round(period, 2)
        amplitudes[pair] = round(amplitude, 4)  # raw, for the corridor brake
        time.sleep(0.15)
    state["scores"] = scores
    state["wave_period_hours"] = periods
    state["amplitudes"] = amplitudes

    # --- publish ---
    atomic_write(PAIRLIST_FILE, {
        "pairs": list(state["active"].keys()),
        "refresh_period": settings["refresh_seconds"],
    })
    atomic_write(STATE_FILE, state)
    log(f"active list ({len(state['active'])}): {', '.join(state['active'])}")


def main() -> None:
    once = "--once" in sys.argv
    while True:
        try:
            run_cycle()
        except Exception as exc:
            log(f"cycle failed (will retry): {exc}")
        if once:
            break
        time.sleep(load_settings()["refresh_seconds"])


if __name__ == "__main__":
    main()
