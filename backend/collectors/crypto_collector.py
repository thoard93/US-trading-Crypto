import ccxt
import pandas as pd
import time

class CryptoCollector:
    def __init__(self, exchange_id='kraken', api_key=None, api_secret=None):
        import os
        # Prioritize provided keys, then fallback to env
        # 🛡️ RESILIENCE: Remove all whitespace/newlines from terminal copy-pastes
        api_key = (api_key or os.getenv('KRAKEN_API_KEY', ''))
        api_key = "".join(api_key.split()) if api_key else None
        
        api_secret = (api_secret or os.getenv('KRAKEN_SECRET_KEY', ''))
        api_secret = "".join(api_secret.split()) if api_secret else None
        
        if api_key and api_secret:
            self.exchange = getattr(ccxt, exchange_id)({
                'apiKey': api_key,
                'secret': api_secret,
                'enableRateLimit': True
            })
            print(f"✅ CryptoCollector initialized with API keys for {exchange_id}.")
        else:
            self.exchange = getattr(ccxt, exchange_id)()
            print(f"⚠️ CryptoCollector initialized WITHOUT API keys for {exchange_id}. Private endpoints will fail.")
        
    def fetch_ohlcv(self, symbol, timeframe='1h', limit=100):
        """
        Fetch OHLCV (Open, High, Low, Close, Volume) data.
        Symbol format: 'BTC/USDT'
        """
        try:
            ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            return df
        except Exception as e:
            print(f"Error fetching data for {symbol}: {e}")
            return None

    def get_current_price(self, symbol):
        """Fetch the current ticker price."""
        try:
            ticker = self.exchange.fetch_ticker(symbol)
            return ticker['last']
        except Exception as e:
            print(f"Error fetching price for {symbol}: {e}")
            return None

if __name__ == "__main__":
    # Quick test
    collector = CryptoCollector()
    price = collector.get_current_price('BTC/USDT')
    print(f"Current BTC Price: {price}")
    data = collector.fetch_ohlcv('BTC/USDT', limit=5)
    print(data)
