set -e
"/c/Program Files/Docker/Docker/resources/bin/docker.exe" compose run --rm freqtrade download-data --config /freqtrade/user_data/config_backtest.json -t 5m 1m --timerange 20210505-20210614 --prepend -p "DOGE/USDT" "BTC/USDT"
"/c/Program Files/Docker/Docker/resources/bin/docker.exe" compose run --rm freqtrade download-data --config /freqtrade/user_data/config_backtest.json -t 5m 1m --timerange 20220428-20220606 --prepend -p "MASK/USDT" "BTC/USDT"
"/c/Program Files/Docker/Docker/resources/bin/docker.exe" compose run --rm freqtrade download-data --config /freqtrade/user_data/config_backtest.json -t 5m 1m --timerange 20220606-20220713 --prepend -p "BTC/USDT"
"/c/Program Files/Docker/Docker/resources/bin/docker.exe" compose run --rm freqtrade download-data --config /freqtrade/user_data/config_backtest.json -t 5m 1m --timerange 20220910-20221109 --prepend -p "INJ/USDT" "SANTOS/USDT" "LAZIO/USDT" "PORTO/USDT" "BTC/USDT"
