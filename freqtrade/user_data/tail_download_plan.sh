set -e
echo "=== tail window 20210512: 11 pairs ==="
"/c/Program Files/Docker/Docker/resources/bin/docker.exe" compose run --rm freqtrade download-data --config /freqtrade/user_data/config_backtest.json -t 5m 1m --timerange 20210505-20210614 -p "BTC/USDT" "CTSI/USDT" "DOGE/USDT" "ETC/USDT" "LSK/USDT" "QTUM/USDT" "RLC/USDT" "STRAX/USDT" "TKO/USDT" "TLM/USDT" "TRB/USDT"
echo "=== tail window 20220505: 11 pairs ==="
"/c/Program Files/Docker/Docker/resources/bin/docker.exe" compose run --rm freqtrade download-data --config /freqtrade/user_data/config_backtest.json -t 5m 1m --timerange 20220428-20220606 -p "APE/USDT" "ASTR/USDT" "BTC/USDT" "CHR/USDT" "ENS/USDT" "FLUX/USDT" "MASK/USDT" "PEOPLE/USDT" "PYR/USDT" "SKL/USDT" "UMA/USDT"
echo "=== tail window 20220613: 11 pairs ==="
"/c/Program Files/Docker/Docker/resources/bin/docker.exe" compose run --rm freqtrade download-data --config /freqtrade/user_data/config_backtest.json -t 5m 1m --timerange 20220606-20220713 -p "ASR/USDT" "BAND/USDT" "BEL/USDT" "BTC/USDT" "DODO/USDT" "GTC/USDT" "LUNA/USDT" "MTL/USDT" "OG/USDT" "RSR/USDT" "TRB/USDT"
echo "=== tail window 20220917: 11 pairs ==="
"/c/Program Files/Docker/Docker/resources/bin/docker.exe" compose run --rm freqtrade download-data --config /freqtrade/user_data/config_backtest.json -t 5m 1m --timerange 20220910-20221109 -p "ATOM/USDT" "BTC/USDT" "INJ/USDT" "LAZIO/USDT" "LDO/USDT" "LUNA/USDT" "PORTO/USDT" "PYR/USDT" "RVN/USDT" "SANTOS/USDT" "TRB/USDT"
