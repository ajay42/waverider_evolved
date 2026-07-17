"""
Monte Carlo bootstrap over backtest results.

Plain idea: a backtest shows ONE ordering of history. Here we reshuffle the
completed DEALS thousands of times (each freqtrade "trade" is one whole deal,
so the orders inside a deal stay together) and rebuild the equity curve each
time. The spread of outcomes answers the capital-safety question a single
backtest can't: "how bad could a plausible unlucky streak have been?"

Honest caveat printed with results: deals overlap in time and alt-coins move
together, so reshuffling understates correlation. Treat the bands as
optimistic bounds, not guarantees.

Usage:
    python user_data/scripts/monte_carlo.py                    # matrix + tail results
    python user_data/scripts/monte_carlo.py --paths 5000
    python user_data/scripts/monte_carlo.py --only tail
"""

import glob
import json
import random
import sys
import zipfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

USER_DATA = Path(__file__).resolve().parents[1]
WALLET = 10_000.0
DEFAULT_PATHS = 5000


def load_deals(path: Path) -> list:
    with zipfile.ZipFile(path) as z:
        name = [n for n in z.namelist()
                if n.endswith(".json") and "meta" not in n and "config" not in n][0]
        data = json.loads(z.read(name))
    res = list(data["strategy"].values())[0]
    return [t["profit_abs"] for t in res["trades"]]


def bootstrap(deals: list, n_paths: int, rng: random.Random) -> dict:
    """Resample deals with replacement; rebuild equity paths; collect stats."""
    n = len(deals)
    max_dds, finals = [], []
    for _ in range(n_paths):
        equity = peak = 0.0
        max_dd = 0.0
        for _ in range(n):
            equity += deals[rng.randrange(n)]
            peak = max(peak, equity)
            max_dd = max(max_dd, peak - equity)
        max_dds.append(max_dd)
        finals.append(equity)
    max_dds.sort()
    finals.sort()

    def pct(sorted_list, p):
        return sorted_list[min(int(p / 100 * len(sorted_list)), len(sorted_list) - 1)]

    return {
        "n_deals": n,
        "dd_median": pct(max_dds, 50),
        "dd_p95": pct(max_dds, 95),
        "dd_p99": pct(max_dds, 99),
        "final_p5": pct(finals, 5),
        "final_median": pct(finals, 50),
        "p_loss": sum(1 for f in finals if f < 0) / len(finals),
    }


def main():
    n_paths = DEFAULT_PATHS
    if "--paths" in sys.argv:
        n_paths = int(sys.argv[sys.argv.index("--paths") + 1])
    only = sys.argv[sys.argv.index("--only") + 1] if "--only" in sys.argv else None

    dirs = [d for d in ("matrix", "tail")
            if (only is None or d == only)]
    rng = random.Random(42)  # reproducible

    print(f"Monte Carlo bootstrap - {n_paths} reshuffled paths per run, "
          f"deal-level blocks, seed 42")
    print("CAVEAT: reshuffling treats deals as independent; real alt-coins")
    print("crash together, so true tails are worse than these bands.\n")

    header = (f"{'run':<30} {'deals':>5} {'ddP50$':>7} {'ddP95$':>7} {'ddP99$':>7} "
              f"{'ddP99%':>6} {'P5 final$':>9} {'P(loss)':>7}")
    for d in dirs:
        paths = sorted(glob.glob(str(USER_DATA / "backtest_results" / d / "*.zip")))
        if not paths:
            continue
        print(f"=== {d.upper()} results ===")
        print(header)
        for path in paths:
            run_id = Path(path).stem
            try:
                deals = load_deals(Path(path))
                if len(deals) < 10:
                    print(f"{run_id:<30} too few deals, skipped")
                    continue
                s = bootstrap(deals, n_paths, rng)
                print(f"{run_id:<30} {s['n_deals']:>5} {s['dd_median']:>7.0f} "
                      f"{s['dd_p95']:>7.0f} {s['dd_p99']:>7.0f} "
                      f"{100 * s['dd_p99'] / WALLET:>5.1f}% "
                      f"{s['final_p5']:>9.1f} {s['p_loss']:>6.1%}")
            except Exception as exc:
                print(f"{run_id:<30} error: {exc}")
        print()


if __name__ == "__main__":
    main()
