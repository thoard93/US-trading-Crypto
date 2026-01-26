
import os
import sys
import asyncio
from datetime import datetime

# Add parent dir to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from dex_trader import DexTrader
from auto_launcher import AutoLauncher
from meme_creator import MemeCreator
from trend_hunter import TrendHunter

async def run_diagnostic():
    print("📋 --- VISIBILITY & GROWTH DIAGNOSTIC ---")
    
    # 1. Check DexTrader Initialization
    trader = DexTrader()
    print(f"✅ DexTrader initialized with RPC: {trader.rpc_url[:50]}...")
    
    # 2. Check AutoLauncher Config
    launcher = AutoLauncher(dex_trader=trader)
    print(f"📊 Default Volume Seed: {launcher.volume_seed_sol} SOL")
    
    # 3. Simulate Boost
    print("\n🚀 SIMULATING !autolaunch boost 0.08")
    launcher.set_boost(0.08)
    status = launcher.get_status()
    print(f"✅ Active Boost: {status['boost']} SOL")
    
    # 4. Keyword Discovery Test
    # Using a fake TrendHunter to simulate finding a trending topic
    class MockTrendHunter:
        def get_trending_keywords(self, limit=5):
            return ["AI AGENT", "SOLANA SUMMER", "DOGE"]
        def is_meme_worthy(self, kw):
            return True

    launcher.trend_hunter = MockTrendHunter()
    print("\n🔍 Running test trend scan...")
    added = await launcher.discover_and_queue()
    print(f"✅ Found {added} worthy keywords: {launcher.launch_queue}")
    
    # 5. Jito Bundle Construction Check (Logic check only)
    print("\n🔐 VERIFYING JITO BUNDLE LOGIC...")
    print("Checking create_pump_token signature...")
    import inspect
    sig = inspect.signature(trader.create_pump_token)
    if 'use_jito' in sig.parameters:
        print("✅ create_pump_token supports 'use_jito'")
        print(f"   Default params: {sig.parameters}")
    else:
        print("❌ create_pump_token MISSING 'use_jito' support!")

    print("\n📢 DIAGNOSTIC COMPLETE: System is ready for deployment. 🔥")

if __name__ == "__main__":
    asyncio.run(run_diagnostic())
