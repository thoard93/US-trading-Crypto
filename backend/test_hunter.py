import os
import sys
import asyncio
import logging

# Add backend to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Load env including Helius Key
env_path = os.path.join(os.path.dirname(__file__), '.env')
with open(env_path, 'r') as f:
    for line in f:
        if line.strip() and not line.startswith('#'):
            key, val = line.strip().split('=', 1)
            os.environ[key] = val

from backend.analysis.copy_trader import SmartCopyTrader

logging.basicConfig(level=logging.INFO)

async def test_hunt():
    print("Initializing SmartCopyTrader...")
    hunter = SmartCopyTrader()
    
    print("Scanning Market (Limited Scope)...")
    await hunter.scan_market_for_whales(max_pairs=2, max_traders_per_pair=5)
    
    print("\n--- HUNT RESULTS ---")
    print(f"Qualified Wallets: {len(hunter.qualified_wallets)}")
    for w, data in hunter.qualified_wallets.items():
        print(f"Wallet: {w} | Score: {data['score']} | P10: {data['stats']['p10_holding_time_sec']}s")

if __name__ == "__main__":
    asyncio.run(test_hunt())
