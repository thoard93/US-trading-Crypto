
import os
from alpaca_trade_api.rest import REST
from dotenv import load_dotenv

load_dotenv()

def test_alpaca():
    api_key = os.getenv('ALPACA_API_KEY', '').strip()
    secret_key = os.getenv('ALPACA_SECRET_KEY', '').strip()
    base_url = os.getenv('ALPACA_BASE_URL', 'https://paper-api.alpaca.markets').strip()
    
    print(f"Testing Alpaca with Key: {api_key[:5]}... (Base: {base_url})")
    
    if not api_key or not secret_key:
        print("❌ Alpaca keys missing from environment.")
        return
        
    try:
        api = REST(api_key, secret_key, base_url)
        account = api.get_account()
        print(f"✅ Success! Account Status: {account.status}")
        print(f"💰 Equity: ${account.equity}")
        
        # Test data fetch
        snapshot = api.get_snapshot("AAPL")
        print(f"🍎 AAPL Price: ${snapshot.latest_trade.price}")
        
    except Exception as e:
        print(f"❌ Alpaca Connection Failed: {e}")

if __name__ == "__main__":
    test_alpaca()
