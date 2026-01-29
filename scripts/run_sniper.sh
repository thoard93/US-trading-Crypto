#!/bin/bash
# Market Sniper Launcher - Sources .env and runs with proper logging

set -e

cd /opt/US-trading-Crypto/backend

# Source environment variables (handle both export VAR=val and VAR=val formats)
if [ -f .env ]; then
    set -a
    source .env
    set +a
fi

# Export PATH for Python
export PATH="/usr/local/bin:/usr/bin:$PATH"
export PYTHONUNBUFFERED=1

echo "=== MARKET SNIPER STARTING ==="
echo "Time: $(date)"
echo "Wallet: $SOLANA_PRIVATE_KEY" | head -c 30
echo "..."
echo "================================"

exec /usr/bin/python3 -u /opt/US-trading-Crypto/backend/market_sniper.py
