set -e
echo "=== window 20241106: 20 pairs ==="
"/c/Program Files/Docker/Docker/resources/bin/docker.exe" compose run --rm freqtrade download-data --config /freqtrade/user_data/config_backtest.json -t 5m 1m --timerange 20241030-20241211 -p "ARKM/USDT" "BAR/USDT" "BICO/USDT" "BNB/USDT" "BTC/USDT" "DOGE/USDT" "ETH/USDT" "LAZIO/USDT" "MASK/USDT" "NEIRO/USDT" "OGN/USDT" "PEPE/USDT" "PORTO/USDT" "RARE/USDT" "RAY/USDT" "SANTOS/USDT" "SOL/USDT" "SUI/USDT" "WIF/USDT" "XRP/USDT"
echo "=== window 20260302: 20 pairs ==="
"/c/Program Files/Docker/Docker/resources/bin/docker.exe" compose run --rm freqtrade download-data --config /freqtrade/user_data/config_backtest.json -t 5m 1m --timerange 20260223-20260426 -p "BNB/USDT" "BTC/USDT" "DOGE/USDT" "ENSO/USDT" "ESP/USDT" "ETH/USDT" "FOGO/USDT" "KITE/USDT" "OP/USDT" "PAXG/USDT" "PEPE/USDT" "PUMP/USDT" "SOL/USDT" "SUI/USDT" "VIRTUAL/USDT" "WIF/USDT" "XRP/USDT" "ZAMA/USDT" "ZEC/USDT" "ZRO/USDT"
echo "=== window 20260602: 17 pairs ==="
"/c/Program Files/Docker/Docker/resources/bin/docker.exe" compose run --rm freqtrade download-data --config /freqtrade/user_data/config_backtest.json -t 5m 1m --timerange 20260526-20260702 -p "ALLO/USDT" "AR/USDT" "BNB/USDT" "BTC/USDT" "ETH/USDT" "FET/USDT" "HEI/USDT" "INJ/USDT" "JTO/USDT" "NEAR/USDT" "SOL/USDT" "SUI/USDT" "WLD/USDT" "XLM/USDT" "XPL/USDT" "XRP/USDT" "ZEC/USDT"
