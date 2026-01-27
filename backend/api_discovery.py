"""
Pump.fun API Endpoint Discovery
Find ALL endpoints including lower MC movers
"""
import requests
import json

def test_endpoints():
    """Test various Pump.fun API endpoints"""
    
    endpoints = [
        # Known endpoints
        ("TOP RUNNERS (Big MC)", "https://frontend-api-v3.pump.fun/coins/top-runners"),
        
        # Possible movers/hot endpoints
        ("COINS LIST", "https://frontend-api-v3.pump.fun/coins?limit=50&sort=last_trade_timestamp&order=DESC"),
        ("COINS BY VOLUME", "https://frontend-api-v3.pump.fun/coins?limit=50&sort=volume&order=DESC"),
        ("COINS NEW", "https://frontend-api-v3.pump.fun/coins?limit=50&sort=created_timestamp&order=DESC"),
        ("COINS HOT", "https://frontend-api-v3.pump.fun/coins/hot"),
        ("COINS TRENDING", "https://frontend-api-v3.pump.fun/coins/trending"),
        ("COINS MOVERS", "https://frontend-api-v3.pump.fun/coins/movers"),
        
        # King of the hill
        ("KING OF HILL", "https://frontend-api-v3.pump.fun/coins/king-of-the-hill"),
        ("FEATURED", "https://frontend-api-v3.pump.fun/coins/featured"),
        
        # Graduated/bonding
        ("COMPLETING", "https://frontend-api-v3.pump.fun/coins/completing"),
        ("GRADUATED", "https://frontend-api-v3.pump.fun/coins/graduated"),
        
        # Different base URLs
        ("CLIENT API COINS", "https://client-api-2-74b1891ee9f9.herokuapp.com/coins?limit=30"),
        
        # With filters
        ("LOW MC FILTER", "https://frontend-api-v3.pump.fun/coins?limit=50&minMarketCap=3000&maxMarketCap=10000"),
    ]
    
    for name, url in endpoints:
        print(f"\n{'='*80}")
        print(f"{name}")
        print(f"URL: {url}")
        print(f"{'='*80}")
        
        try:
            resp = requests.get(url, timeout=10, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept': 'application/json',
                'Origin': 'https://pump.fun',
                'Referer': 'https://pump.fun/',
            })
            
            print(f"Status: {resp.status_code}")
            
            if resp.status_code == 200:
                data = resp.json()
                
                # Handle different formats
                if isinstance(data, list):
                    tokens = data
                elif isinstance(data, dict):
                    tokens = data.get('coins', data.get('data', data.get('tokens', [data] if 'mint' in data else []))
                else:
                    tokens = []
                
                print(f"Tokens: {len(tokens)}")
                
                # Show first few with MC
                for i, t in enumerate(tokens[:5]):
                    # Handle nested coin structure
                    if 'coin' in t:
                        t = t['coin']
                    
                    symbol = t.get('symbol', '?')
                    usd_mc = t.get('usd_market_cap', 0)
                    mc = t.get('market_cap', 0)
                    replies = t.get('reply_count', 0)
                    
                    mc_display = f"${usd_mc:,.0f}" if usd_mc else f"{mc:,.0f} SOL"
                    print(f"  {i+1}. {symbol:12} | MC: {mc_display:>12} | Replies: {replies}")
                
                if len(tokens) > 5:
                    print(f"  ... and {len(tokens)-5} more")
                    
            else:
                print(f"Error: {resp.text[:200]}")
                
        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    test_endpoints()
