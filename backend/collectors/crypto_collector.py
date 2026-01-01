import ccxt
import pandas as pd
import time

class CryptoCollector:
    def __init__(self, exchange_id='binance'):
        self.exchange = getattr(ccxt, exchange_id)()
        
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
