# WaveRider — Cloud Deployment Plan

How we take this from local dry-run to a live small-fund account on a cloud
server, safely. Split into **what Claude does** (all the infra/automation) and
**what you do** (the two things I must never touch: paying for the server and
entering the Binance API keys).

Guiding rule, unchanged: **capital safety before returns.** We compress the
pure-paper stage (you want a small live account as the real teacher) but keep
every safety rail.

---

## 0. Host choice (you pay, I configure)

A small always-on VPS is plenty — the bot is light; Docker + two containers.

| Option | Spec | ~Cost/mo | Notes |
|---|---|---|---|
| Hetzner CX22 | 2 vCPU / 4 GB | ~€4 | best value, EU |
| DigitalOcean | 2 vCPU / 4 GB | ~$12 | simplest UX |
| Contabo VPS S | 4 vCPU / 8 GB | ~$6 | most RAM/€ |

Recommendation: **Hetzner CX22** (cheap, reliable, EU low-latency to Binance).
Pick a region close to Binance's servers (EU/Asia) for lower order latency.
**You:** create the account + pay. **Me:** everything after you hand me SSH.

---

## 1. Server hardening (Claude does)

- Create a non-root `waverider` user; SSH-key login only; disable password &
  root SSH.
- UFW firewall: allow SSH (22) only; **FreqUI (8080) NOT exposed to the
  internet** — reached via SSH tunnel (`ssh -L 8080:localhost:8080 ...`).
- `fail2ban`, unattended security upgrades, swap file.
- Install Docker + Docker Compose.

## 2. Deploy the stack (Claude does)

- `git clone` the repo (once it's pushed).
- Create `config.json` from a committed `config.example.json` template — the
  real one stays off git (secrets). Set a strong FreqUI password + fresh
  `jwt_secret_key`.
- `docker compose up -d` → `freqtrade` + `freqtrade-pairlist`.
- Add: auto-restart (`restart: unless-stopped`, already set), log rotation, a
  daily healthcheck cron, and a disk-space guard.

## 3. Binance API keys (YOU create + enter — I never see them)

When we're ready for live (Stage B below), you create an API key with these
**exact** settings — I'll walk you through the screen:

- **Enable Spot & Margin Trading**: ON (spot only — the strategy is spot).
- **Enable Withdrawals**: **OFF** (non-negotiable — a leaked key then can't
  drain funds).
- **Enable Futures**: OFF.
- **Restrict access to trusted IPs**: ON → the VPS's IP only.
- Paste the key/secret **directly into `config.json` on the server yourself**
  (or via a password-manager credential tool). I never handle the values.

## 4. Go-live stages (compressed for a small live fund)

| Stage | What | Duration | Gate to advance |
|---|---|---|---|
| **A. Cloud dry-run** | Same code, `dry_run: true`, live Binance data | 2–3 days | Runs 24/7 no crashes; behaviour matches local; FreqUI reachable via tunnel |
| **B. Small live fund** | `dry_run: false`, keys locked per §3, **small** capital (e.g. a few hundred USDT), per-coin cap lowered to match | ongoing | Live fills match paper logic; governors + 5-day cap fire as expected |
| **C. Scale** | Raise per-coin cap / capital gradually | your call | Only after B behaves for a few weeks |

Stage A is short on purpose — it's the "does it survive 24/7 on real infra"
smoke, not a long paper trial. Stage B is where the real learning happens, at a
size where a worst case is a tuition fee, not a wound. The per-coin USD cap and
aggregate ceiling scale down with the fund, so worst-case loss is always
bounded and known in advance.

## 5. Monitoring & upkeep (Claude sets up)

- **Weekly trade summary** (`weekly_summary.py`) — every week: what traded,
  win/loss, governor/age-cap events, current exposure, and concrete
  improvement suggestions. Delivered as a file (and optionally Telegram).
- FreqUI via SSH tunnel for live inspection.
- Alert on: crash-freeze engaged, container down, disk full, any traceback.
- Monthly: re-run the offline relearn cycle → review any candidate config diff
  before applying (never auto-applied).

## 6. Division of labour (summary)

| You | Claude |
|---|---|
| Pay for the VPS | Harden server, install Docker |
| Create/enter Binance API keys (§3) | Deploy stack, configure FreqUI securely |
| Approve go-live at each stage | Set up monitoring, weekly summary, alerts |
| Fund the account | Run the berserk validation before live |

---

**Prerequisite before any of this:** finish the R&D sprint (validation +
report) so we deploy the *final validated* strategy, and complete the "berserk"
stress/theory-testing pass. Deployment starts once that's green.
