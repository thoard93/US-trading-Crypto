import asyncio
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.collectors.dex_scout import DexScout

async def test():
    print("Testing DexScout...")
    scout = DexScout()
    pairs = await scout.get_trending_solana_pairs(min_liquidity=100) 
    print(f"Pairs Found: {len(pairs)}")
    if pairs: 
        print(f"Top 1: {pairs[0].get('baseToken', {}).get('symbol')}")
    else:
        print("No pairs found. Check API or filters.")

import logging
logging.basicConfig(level=logging.INFO)

if __name__ == "__main__":
    asyncio.run(test())
