import os
import sys

# Add backend to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.collectors.wallet_collector import WalletCollector

# Manually load .env for test
env_path = os.path.join(os.path.dirname(__file__), '.env')
with open(env_path, 'r') as f:
    for line in f:
        if line.strip() and not line.startswith('#'):
            key, val = line.strip().split('=', 1)
            os.environ[key] = val

def test_crawler():
    collector = WalletCollector()
    wallet = "HiTW2zjAsP5T5Wa7Aptfq7DojHsCQHkd4MbJJL5TGoaX"
    print(f"Testing Crawler on: {wallet}")
    print(f"Helius Key Present: {bool(collector.helius_key)}")
    
    print("Fetching History...")
    stats = collector.analyze_wallet(wallet, lookback_txs=100)
    
    print("\n--- RESULTS ---")
    import json
    print(json.dumps(stats, indent=2))

if __name__ == "__main__":
    test_crawler()
