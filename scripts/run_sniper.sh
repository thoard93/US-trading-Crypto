#!/bin/bash
cd /opt/US-trading-Crypto/backend
source /opt/US-trading-Crypto/backend/.env 2>/dev/null || true
exec /usr/bin/python3 /opt/US-trading-Crypto/backend/market_sniper.py
