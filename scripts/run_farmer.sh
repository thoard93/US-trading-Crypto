#!/bin/bash
# Airdrop Farmer Launcher — Sources .env and runs once (cron handles scheduling)

set -e

cd /opt/US-trading-Crypto/backend

# Source environment variables
if [ -f .env ]; then
    set -a
    source .env
    set +a
fi

# Export PATH for Python
export PATH="/usr/local/bin:/usr/bin:$PATH"
export PYTHONUNBUFFERED=1

echo "=== AIRDROP FARMER STARTING ==="
echo "Time: $(date)"
echo "================================"

exec /usr/bin/python3 -u /opt/US-trading-Crypto/backend/airdrop_farmer.py
