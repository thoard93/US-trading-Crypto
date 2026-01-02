import os
import pandas as pd
from datetime import datetime, timedelta
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
            
            # Calculate start date based on timeframe and limit
            # For hourly bars, go back ~2 weeks to ensure we get enough bars
            if timeframe == '1Hour':
                start = datetime.now() - timedelta(days=14)
            elif timeframe == '1Day':
                start = datetime.now() - timedelta(days=limit + 10)
            else:
                start = datetime.now() - timedelta(hours=limit * 2)
            
            # Format for Alpaca API
            start_str = start.strftime('%Y-%m-%d')
            
            # Fetch historical bars with explicit start date
            bars = self.api.get_bars(
                symbol, 
                tf, 
                start=start_str,
                limit=min(limit, 500)
            ).df
            
            if bars.empty:
                print(f"⚠️ No bars returned for {symbol}")
                return None
            
            # Standardize column names for the Technical Engine
            bars = bars.reset_index()
            bars = bars.rename(columns={
                'timestamp': 'timestamp', 
                'open': 'open', 
                'high': 'high', 
                'low': 'low', 
                'close': 'close', 
                'volume': 'volume'
            })
            
            print(f"📊 Fetched {len(bars)} bars for {symbol}")
            return bars
        except Exception as e:
            print(f"Error fetching stock data for {symbol}: {e}")
            return None

    def get_current_price(self, symbol):
        """Fetch the latest trade price."""
        data = self.get_stock_data(symbol)
        return data['price'] if data else None

    def get_stock_data(self, symbol):
        """Fetch latest price and 24h change using get_snapshot."""
        if not self.api:
            return None
        try:
            snapshot = self.api.get_snapshot(symbol)
            price = snapshot.latest_trade.price
            prev_close = snapshot.prev_daily_bar.close if snapshot.prev_daily_bar else price
            change = ((price / prev_close) - 1) * 100 if prev_close else 0.0
            return {
                "price": price,
                "change": round(change, 2)
            }
        except Exception as e:
            print(f"Error fetching snapshot for {symbol}: {e}")
            return None

    def get_account(self):
        """Get account info including buying power."""
        if not self.api:
            return None
        try:
            account = self.api.get_account()
            return {
                "buying_power": float(account.buying_power),
                "cash": float(account.cash),
                "portfolio_value": float(account.portfolio_value),
                "equity": float(account.equity)
            }
        except Exception as e:
            print(f"Error getting account: {e}")
            return None
    
    def get_position(self, symbol):
        """Get current position for a symbol."""
        if not self.api:
            return None
        try:
            position = self.api.get_position(symbol)
            return {
                "qty": float(position.qty),
                "avg_entry_price": float(position.avg_entry_price),
                "market_value": float(position.market_value),
                "unrealized_pl": float(position.unrealized_pl)
            }
        except:
            return None  # No position
    
    def buy_stock(self, symbol, notional=None, qty=None):
        """
        Buy stock using Alpaca.
        notional: Dollar amount to buy (e.g., $10)
        qty: Number of shares (for whole shares only)
        """
        if not self.api:
            return {"error": "Alpaca not initialized"}
        
        try:
            if notional:
                # Fractional shares - buy by dollar amount
                order = self.api.submit_order(
                    symbol=symbol,
                    notional=notional,
                    side='buy',
                    type='market',
                    time_in_force='day'
                )
            elif qty:
                # Whole shares
                order = self.api.submit_order(
                    symbol=symbol,
                    qty=qty,
                    side='buy',
                    type='market',
                    time_in_force='day'
                )
            else:
                return {"error": "Must specify notional or qty"}
            
            print(f"✅ STOCK BUY ORDER: {symbol} - Order ID: {order.id}")
            return {
                "success": True,
                "order_id": order.id,
                "symbol": symbol,
                "side": "buy",
                "notional": notional,
                "qty": qty
            }
        except Exception as e:
            print(f"❌ Stock buy error for {symbol}: {e}")
            return {"error": str(e)}
    
    def sell_stock(self, symbol, qty=None, percentage=100):
        """Sell stock position."""
        if not self.api:
            return {"error": "Alpaca not initialized"}
        
        try:
            position = self.get_position(symbol)
            if not position:
                return {"error": f"No position in {symbol}"}
            
            sell_qty = position['qty'] if percentage == 100 else position['qty'] * (percentage / 100)
            
            order = self.api.submit_order(
                symbol=symbol,
                qty=sell_qty,
                side='sell',
                type='market',
                time_in_force='day'
            )
            
            print(f"✅ STOCK SELL ORDER: {symbol} - Order ID: {order.id}")
            return {
                "success": True,
                "order_id": order.id,
                "symbol": symbol,
                "side": "sell",
                "qty": sell_qty
            }
        except Exception as e:
            print(f"❌ Stock sell error for {symbol}: {e}")
            return {"error": str(e)}
