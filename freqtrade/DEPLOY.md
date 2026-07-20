# WaveRider — Deploy on any Freqtrade server

Self-contained deploy guide. Works on any Linux box with Docker. No secrets are
in this repo — you supply them at deploy time.

## Prerequisites
- A Linux server (1 vCPU / 2 GB RAM + swap is enough for dry-run)
- Docker + Docker Compose (`curl -fsSL https://get.docker.com | sudo sh`)

## 1. Get the code onto the server
```
git clone https://github.com/ajay42/waverider_evolved.git
cd waverider_evolved/freqtrade
```
(or copy the `waverider-portable/` folder over — it's the same runtime subset.)

## 2. Create your config from the template
```
cp user_data/config.example.json user_data/config.json
```
Then edit `user_data/config.json`:
- `api_server.password` → set a strong FreqUI password
- `api_server.jwt_secret_key` → a random 64-hex string (`openssl rand -hex 32`)
- `api_server.ws_token` → a random token (`openssl rand -base64 24`)
- `dry_run` stays `true`, `dry_run_wallet` → your paper wallet size
- Leave `exchange.key` / `exchange.secret` empty for now (dry-run needs none)

## 3. Launch (dry-run first — always)
```
docker compose up -d
docker compose ps                       # both up?
docker logs freqtrade --tail 40         # trading?
docker logs freqtrade-pairlist --tail 20  # picking coins?
```

## 4. Watch it (FreqUI)
FreqUI binds to `127.0.0.1:8080` on the server (never internet-exposed). Reach
it via SSH tunnel from your PC:
```
ssh -L 8080:localhost:8080 <user>@<server-ip>
```
then open http://localhost:8080 (login = the api_server creds above).

## 5. Go live (only after a stability soak)
1. Create a Binance API key: **Spot ON, Withdrawals OFF, Futures OFF,
   IP-restricted to the server**.
2. Enter keys (hidden input, stays paper): `python3 scripts/set_keys.py`
   *(adjust the path if your layout differs)*
3. Flip live: set `"dry_run": false` in config.json, then
   `docker compose restart freqtrade`.
   **Important:** if the bot ran in dry-run first, delete the DB before going
   live so simulated trades don't confuse it:
   `docker compose stop freqtrade && rm user_data/tradesv3.sqlite && docker compose up -d`

## Safety notes
- `weekly_summary.py` → weekly digest + suggestions.
- Emergency stop: `docker compose stop freqtrade`.
- Never commit `config.json` (it holds secrets — already gitignored).
- Read `../STRATEGY_REFERENCE.md` and `CAPITAL_SAFETY.md` before live money.
- Sizing: per-coin cap × max_coins is your absolute worst-case exposure; scale
  it to your wallet (keep per-coin cap ≈ 10% of wallet).
