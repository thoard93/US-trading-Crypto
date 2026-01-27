"""
Pump.fun Movers Research - Debug Version
First let's see what the API actually returns
"""
import requests
import json

def fetch_and_debug():
    """Fetch movers and print raw response"""
    endpoints = [
        "https://frontend-api.pump.fun/coins/top-runners",
        "https://frontend-api-v3.pump.fun/coins/top-runners",
        "https://frontend-api.pump.fun/coins/trending",
        "https://client-api-2-74b1891ee9f9.herokuapp.com/coins?sort=market_cap&order=DESC&limit=30",
    ]
    
    print("Testing Pump.fun API endpoints...\n")
    
    for endpoint in endpoints:
        print(f"{'='*80}")
        print(f"ENDPOINT: {endpoint}")
        print(f"{'='*80}")
        try:
            resp = requests.get(endpoint, timeout=10, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept': 'application/json',
            })
            print(f"Status: {resp.status_code}")
            
            if resp.status_code == 200:
                data = resp.json()
                
                # Handle different formats
                if isinstance(data, list):
                    tokens = data
                elif isinstance(data, dict):
                    tokens = data.get('coins', data.get('data', data.get('tokens', [])))
                    if not tokens and 'mint' in data:
                        tokens = [data]  # Single token response
                else:
                    tokens = []
                
                print(f"Tokens found: {len(tokens)}")
                
                if tokens and len(tokens) > 0:
                    print(f"\nFIRST TOKEN RAW DATA:")
                    print(json.dumps(tokens[0], indent=2, default=str)[:2000])
                    
                    print(f"\nALL FIELD NAMES:")
                    for key in tokens[0].keys():
                        print(f"  - {key}")
                    
                    # Try to extract useful info
                    t = tokens[0]
                    print(f"\nEXTRACTED:")
                    print(f"  name: {t.get('name', t.get('token_name', 'N/A'))}")
                    print(f"  symbol: {t.get('symbol', t.get('ticker', 'N/A'))}")
                    print(f"  mint: {t.get('mint', t.get('address', t.get('token_address', 'N/A')))}")
                    print(f"  market_cap: {t.get('market_cap', t.get('marketCap', t.get('usd_market_cap', 'N/A')))}")
                    print(f"  reply_count: {t.get('reply_count', t.get('replyCount', t.get('replies', 'N/A')))}")
                    
                    print(f"\n--- SUCCESS! This endpoint works ---")
                    return tokens
            else:
                print(f"Failed with status {resp.status_code}")
                print(f"Response: {resp.text[:500]}")
                
        except Exception as e:
            print(f"Error: {e}")
        
        print()
    
    return []

if __name__ == "__main__":
    tokens = fetch_and_debug()
    
    if not tokens:
        print("\nNo working endpoint found. Pump.fun may have changed their API.")
        print("Alternative: Use Bitquery GraphQL API or scrape the website directly.")
