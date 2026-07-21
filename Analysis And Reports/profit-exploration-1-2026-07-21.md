# Profit Exploration #1 — Levers #3 (selection) & #4 (concentration)

Tested 2026-07-21. 20 backtests (5 windows × 4 variants), full safety stack +
5-day age cap ON in every variant. Verdict rule: a lever wins only if it beats
the live baseline's profit **and** holds drawdown/deployment.

## Result (averaged across crash2021, bear2022b, ftxchop, valchop26, valbear26)

| Variant | Avg profit | Avg dd | Avg peak-deploy |
|---|---|---|---|
| live (baseline) | −0.33% | 0.60% | 5.2% |
| #3 waveup (chop + updrift) | −0.29% | 0.54% | 5.3% |
| **#4a conc_deep (top-5, 2× cap, deeper ladders)** | **−0.17%** | **0.33%** | **2.8%** |
| #4b conc_big (top-5, 2× cap, 2× order size) | −0.35% | 0.66% | 5.5% |

Standout single window — 2021 crash: conc_deep −0.77% vs live −1.54% (loss
halved, dd 1.02% vs 1.80%).

## Verdicts

- **#3 waveup — REJECT.** Marginal vs baseline and *worse* in the valbear26
  hold-out (−0.25% vs −0.16%). A signed-drift bonus on the selector does not
  reliably help; it drifts toward trendier coins (the selector's known weak
  spot). Not adopted.
- **#4b conc_big — REJECT.** Bigger orders deploy more, draw down more, and
  return less — worst in the crash. This is "buying return with risk," which
  CAPITAL_SAFETY.md forbids. Not adopted.
- **#4a conc_deep — PROMISING (safety/efficiency win, not a profit unlock).**
  Beats live on every average axis: better return, ~half the drawdown, ~half
  the capital deployed. Concentrating on the 5 best coins with deeper ladders
  needs less capital and behaves better in crashes. Worth carrying forward as a
  reviewed candidate — but it is NOT proven to make money, only to run the same
  strategy more safely.

## Honest limitations

- **No bull/uptrend window tested** — every window is a crash/bear/chop, so the
  actual *profit* potential of any lever is unmeasured. This is the #1 gap.
- Concentration numbers in valbear26 rest on very few trades (top-5 barely
  traded that month) — treat that window's conc results as low-confidence.
- Backtest wallet is 10k; on the live 500 account, "conc_deep" means the
  CONCEPT (5 coins, deeper ladders) with wallet-appropriate caps (~$100/coin),
  not the literal $2000 cap.

## Recommended next steps

1. **Add a bull-market window** (e.g., a 2021 or 2023/2024 uptrend) and re-run
   all variants — this is the only way to answer "can it make money."
2. **Test the untried exit/entry levers** there too: #1 dynamic take-profit
   (scale TP with wave size) and #2 entry-timing (don't open into a fresh dump)
   — exit/entry are more likely profit levers than selection proved to be.
3. If conc_deep survives a bull window + the adversarial gate, produce it as a
   wallet-sized candidate config for review (never auto-applied).

**Bottom line:** selection and bet-size are NOT the profit lever. The strategy
stays capital-preserving. The one keeper — conc_deep — makes it *safer*, not
richer. The profit question is genuinely open until favorable markets are tested.
