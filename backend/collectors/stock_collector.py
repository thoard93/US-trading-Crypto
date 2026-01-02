import os
import pandas as pd
from alpaca_trade_api.rest import REST, TimeFrame
from dotenv import load_dotenv

load_dotenv()

class StockCollector:
    def __init__(self, api_key=None, secret_key=None, base_url=None):
        # Prioritize provided keys, then fallback to env
        self.api_key = api_key or os.getenv('ALPACA_API_KEY')
        self.secret_key = secret_key or os.getenv('ALPACA_SECRET_KEY')
        self.base_url = base_url or os.getenv('ALPACA_BASE_URL', 'https://paper-api.alpaca.markets')
        
        if self.api_key and self.secret_key:
            self.api = REST(self.api_key, self.secret_key, self.base_url)
            print(f"✅ StockCollector initialized with Alpaca keys (Base: {self.base_url}).")
        else:
            self.api = None
            print("⚠️ StockCollector initialized WITHOUT Alpaca keys. Stock collection disabled.")

    def fetch_ohlcv(self, symbol, timeframe='1Hour', limit=100):
        """
        Fetch OHLCV data for a stock symbol.
        Timeframe: '1Min', '5Min', '15Min', '1Hour', '1Day'
        """
        if not self.api:
            return None
            
        try:
            # Map common strings to Alpaca TimeFrame constants
            tf_map = {
                '1Min': TimeFrame.Minute,
                '5Min': TimeFrame.Minute,
                '1Hour': TimeFrame.Hour,
                '1Day': TimeFrame.Day
            }
            tf = tf_map.get(timeframe, TimeFrame.Hour)
            
            # We use bars for historical/current OHLCV
            bars = self.api.get_bars(symbol, tf, limit=min(limit, 500)).df
            if bars.empty:
                return None
            
            # Standardize column names for the Technical Engine
            bars = bars.reset_index()
            bars = bars.rename(columns={'timestamp': 'timestamp', 'open': 'open', 'high': 'high', 'low': 'low', 'close': 'close', 'volume': 'volume'})
            return bars
        except Exception as e:
            print(f"Error fetching stock data for {symbol}: {e}")
            return None

    def get_current_price(self, symbol):
        """Fetch the latest trade price."""
        if not self.api:
            return None
        try:
            trade = self.api.get_latest_trade(symbol)
            return trade.price
        except Exception as e:
            print(f"Error fetching stock price for {symbol}: {e}")
            return None
