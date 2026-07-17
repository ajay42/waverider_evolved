"""
One-command monitoring table for the whole coin list.

    python user_data/scripts/status.py

Shows every listed coin's wave score (vs the rotation floor), amplitude,
wave period, join time, flags (PARKED / DRAINING / BRAKED), and the open
position if any. Reads the picker's state file + a copy of the trade DB -
no bot interaction, safe to run anytime.
"""

import json
import shutil
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
USER_DATA = Path(__file__).resolve().parents[1]


def main():
    state = json.loads((USER_DATA / "pairlist_state.json").read_text())
    config = json.loads((USER_DATA / "config.json").read_text())
    floor = float(config.get("wave_rider", {}).get("min_active_wave_score", 0))

    tmp = Path(tempfile.mkdtemp()) / "t.sqlite"
    shutil.copy(USER_DATA / "tradesv3.sqlite", tmp)
    wal = USER_DATA / "tradesv3.sqlite-wal"
    if wal.exists():
        shutil.copy(wal, tmp.with_name(tmp.name + "-wal"))
    con = sqlite3.connect(tmp)
    con.row_factory = sqlite3.Row

    open_by_pair = {}
    for r in con.execute(
            "SELECT id, pair, stake_amount, open_rate, open_date FROM trades WHERE is_open=1"):
        open_by_pair[r["pair"]] = r
    braked = set()
    for r in con.execute(
            "SELECT t.pair FROM trade_custom_data d JOIN trades t ON t.id=d.ft_trade_id "
            "WHERE t.is_open=1 AND d.cd_key='coin_braked' AND d.cd_value IN ('1','true')"):
        braked.add(r["pair"])

    now = datetime.now(timezone.utc)
    scores = state.get("scores", {})
    amps = state.get("amplitudes", {})
    periods = state.get("wave_period_hours", {})
    parked = set(state.get("parked", []))
    draining = set(state.get("draining", {}))

    print(f"quality floor: {floor}   parked: {len(parked)}   "
          f"draining: {len(draining)}   time: {now.strftime('%H:%M UTC')}\n")
    header = (f"{'pair':<12} {'score':>6} {'amp%':>6} {'wave-h':>6} "
              f"{'stint':>6} {'flags':<16} {'position':<24}")
    print(header)
    print("-" * len(header))
    for pair, joined_iso in state.get("active", {}).items():
        joined = datetime.fromisoformat(joined_iso)
        stint_h = (now - joined).total_seconds() / 3600
        flags = " ".join(f for f, on in (
            ("PARKED", pair in parked), ("DRAIN", pair in draining),
            ("BRAKED", pair in braked)) if on) or "-"
        t = open_by_pair.get(pair)
        pos = (f"${t['stake_amount']:.0f} @ {t['open_rate']:.6g} "
               f"(#{t['id']})" if t else "flat")
        score = scores.get(pair)
        mark = "!" if (score is not None and floor > 0 and score < floor) else " "
        print(f"{pair:<12} {score if score is not None else '?':>6}{mark}"
              f"{amps.get(pair, '?'):>6} {periods.get(pair, '?'):>6} "
              f"{stint_h:>5.0f}h {flags:<16} {pos:<24}")

    retired = state.get("retired", {})
    if retired:
        print(f"\nretired (cooldown): {', '.join(sorted(retired))}")


if __name__ == "__main__":
    main()
