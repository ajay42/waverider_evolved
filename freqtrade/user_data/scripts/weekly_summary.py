"""
Weekly trade-execution summary + improvement suggestions.

Reads the freqtrade trade DB (dry-run or live - same schema) and produces a
plain-language weekly digest: what traded, win/loss, PnL, exit-reason mix,
governor/age-cap activity, current open exposure - plus concrete, data-driven
improvement suggestions keyed to the win-probability model's danger thresholds.

Run it weekly (manually, or via cron/Telegram later):
    python user_data/scripts/weekly_summary.py [--days 7] [--db PATH]

Writes: Analysis And Reports/weekly/weekly-YYYY-MM-DD.md  (and prints it)
Stdlib only.
"""

import argparse
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

USER_DATA = Path(__file__).resolve().parents[1]
DEFAULT_DB = USER_DATA / "tradesv3.sqlite"
OUT_DIR = USER_DATA.parents[1] / "Analysis And Reports" / "weekly"

# Human labels for exit reasons.
EXIT_LABEL = {
    "grace_full_close": "grace TP (clean trend-dip win)",
    "skim_close": "wave skim (partial)",
    "skim_full_close": "wave skim (full)",
    "grid_close": "grid/governor peel",
    "grid_full_close": "grid/governor full close",
    "phase_d_close": "Phase-D capitulation",
    "drain_close": "drain eviction",
    "age_cap_close": "5-day age cap",
    "force_exit": "manual/force exit",
}


def load_trades(db_path: Path, since: datetime):
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    cols = {r[1] for r in con.execute("PRAGMA table_info(trades)")}
    prof = "close_profit_abs" if "close_profit_abs" in cols else "close_profit"
    rows = con.execute(
        f"SELECT pair, is_open, open_date, close_date, exit_reason, "
        f"stake_amount, close_profit, {prof} AS pnl_abs FROM trades"
    ).fetchall()
    con.close()
    closed, open_now = [], []
    for r in rows:
        if r["is_open"]:
            open_now.append(r)
        elif r["close_date"]:
            cd = datetime.fromisoformat(r["close_date"]).replace(tzinfo=timezone.utc) \
                if "+" not in str(r["close_date"]) else datetime.fromisoformat(r["close_date"])
            if cd >= since:
                closed.append(r)
    return closed, open_now


def suggestions(closed, open_now) -> list:
    """Data-driven tips keyed to the win-model danger thresholds."""
    out = []
    n = len(closed)
    if n == 0:
        return ["No closed trades this week - nothing to tune yet."]
    reasons = Counter(t["exit_reason"] for t in closed)
    age = reasons.get("age_cap_close", 0)
    capit = reasons.get("phase_d_close", 0)
    grid = reasons.get("grid_close", 0) + reasons.get("grid_full_close", 0)
    # Managed exits (drain/age-cap/Phase-D) free stuck capital and are small by
    # design - they are NOT trading losses. A "real loss" is a negative-PnL exit
    # from the profit-taking paths (grace/skim/grid) that we expected to win.
    managed = {"drain_close", "age_cap_close", "phase_d_close"}
    real_losses = [t for t in closed
                   if (t["pnl_abs"] or 0) < 0 and t["exit_reason"] not in managed]
    managed_exits = [t for t in closed if t["exit_reason"] in managed]

    if age >= max(2, n * 0.15):
        out.append(f"{age} deals hit the 5-DAY CAP - those coins stopped waving. "
                   "The selector may be picking trendy (not wavy) coins; consider "
                   "raising the quality floor or reviewing the coin mix.")
    if capit >= max(1, n * 0.10):
        out.append(f"{capit} Phase-D CAPITULATIONS - deals aging to the decision "
                   "phase. Same signal: selection is letting non-wavy coins in.")
    if grid >= n * 0.30:
        out.append(f"{grid} grid/governor peels - the brake/freeze are active a "
                   "lot. Healthy in a falling market; if markets were calm, the "
                   "corridor brake may be too tight.")
    if managed_exits:
        freed = sum(t["pnl_abs"] or 0 for t in managed_exits)
        out.append(f"{len(managed_exits)} managed exits (drain/age-cap/Phase-D) "
                   f"freed stuck capital for {freed:+.2f} USDT total - small by "
                   "design, this is the safety system working, not losses.")
    if real_losses and len(real_losses) / n > 0.05:
        worst = min(t["close_profit"] or 0 for t in real_losses) * 100
        out.append(f"{len(real_losses)} REAL losses ({100*len(real_losses)/n:.0f}% of "
                   f"closes, worst {worst:.1f}%) from profit-taking paths - these are "
                   "the ones to watch. Check if they share deep drawdown (>15%) or "
                   "old age (>12 waves), the win-model's danger zones.")
    # exposure check
    if open_now:
        exp = sum(t["stake_amount"] or 0 for t in open_now)
        out.append(f"Open exposure now ~{exp:.0f} USDT across {len(open_now)} deals. "
                   "Watch it against your aggregate ceiling.")
    if not out:
        out.append("Healthy week - core mechanic (grace/skim wins) dominating, "
                   "governors quiet. No changes indicated.")
    return out


def build(days: int, db_path: Path) -> str:
    since = datetime.now(timezone.utc) - timedelta(days=days)
    closed, open_now = load_trades(db_path, since)
    reasons = Counter(t["exit_reason"] for t in closed)
    total_pnl = sum(t["pnl_abs"] or 0 for t in closed)
    wins = sum(1 for t in closed if (t["pnl_abs"] or 0) > 0)
    n = len(closed)

    L = [f"# Weekly Summary — {datetime.now(timezone.utc):%Y-%m-%d} (last {days}d)", ""]
    L.append(f"- **Closed trades:** {n}")
    if n:
        L.append(f"- **Win rate:** {100*wins/n:.0f}%  ({wins}W / {n-wins}L)")
        L.append(f"- **Net PnL:** {total_pnl:+.2f} USDT")
        L.append(f"- **Open now:** {len(open_now)} deals")
        L.append("")
        L.append("**Exit-reason mix:**")
        for r, c in reasons.most_common():
            L.append(f"  - {c:>3}x  {EXIT_LABEL.get(r, r)}")
    L.append("")
    L.append("## Suggestions for improvement")
    for s in suggestions(closed, open_now):
        L.append(f"- {s}")
    L.append("")
    L.append("*Auto-generated. Exit reasons: grace/skim = the strategy working; "
             "age-cap/Phase-D/drain = capital being freed from stuck deals (small "
             "loss by design, not failure).*")
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--db", type=str, default=str(DEFAULT_DB))
    args = ap.parse_args()
    db = Path(args.db)
    if not db.exists():
        print(f"trade DB not found at {db} - is the bot running / path correct?")
        return
    report = build(args.days, db)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"weekly-{datetime.now(timezone.utc):%Y-%m-%d}.md"
    out.write_text(report, encoding="utf-8")
    print(report)
    print(f"\n(written to {out})")


if __name__ == "__main__":
    main()
