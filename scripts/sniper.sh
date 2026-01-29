#!/bin/bash
# Simple PM2 launcher that sources .env first
cd /opt/US-trading-Crypto/backend
set -a; source .env 2>/dev/null; set +a
exec python3 -u market_sniper.py
