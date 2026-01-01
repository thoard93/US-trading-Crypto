import ccxt
import os
import logging

class TradingExecutive:
    def __init__(self):
        self.api_key = os.getenv('KRAKEN_API_KEY')
        self.secret_key = os.getenv('KRAKEN_SECRET_KEY')
        
        if self.api_key and self.secret_key:
            self.exchange = ccxt.kraken({
                'apiKey': self.api_key,
                'secret': self.secret_key,
                'enableRateLimit': True,
            })
            print("Trading Executive initialized with Kraken API.")
        else:
            self.exchange = None
            print("Warning: Kraken API keys not found. Auto-trading disabled.")

        # Safety Settings
        self.trade_amount_usdt = 10.0  
        self.max_open_trades = 3      
        self.active_positions = {}    # {symbol: {"entry_price": float, "amount": float}}

    def track_position(self, symbol, entry_price, amount):
        """Record an entry for stop-loss monitoring."""
        self.active_positions[symbol] = {
            "entry_price": entry_price,
            "amount": amount
        }

    def check_exit_conditions(self, symbol, current_price):
        """Check if we should exit a trade based on SL/TP."""
        if symbol not in self.active_positions:
            return None

        pos = self.active_positions[symbol]
        entry = pos["entry_price"]
        
        # Stop-Loss: -5%
        if current_price <= entry * 0.95:
            return "STOP_LOSS"
        
        # Take-Profit: +10% 
        if current_price >= entry * 1.10:
            return "TAKE_PROFIT"
            
        return None

    def get_usdt_balance(self):
        """Fetch current USDT balance."""
        if not self.exchange:
            return 0
        try:
            balance = self.exchange.fetch_balance()
            return balance.get('USDT', {}).get('free', 0)
        except Exception as e:
            print(f"Error fetching balance: {e}")
            return 0

    def execute_market_buy(self, symbol, amount_usdt=10.0):
        """Execute a market buy order."""
        if not self.exchange:
            return {"error": "API not configured"}

        try:
            # Check balance first
            balance = self.get_usdt_balance()
            if balance < amount_usdt:
                return {"error": f"Insufficient USDT balance: {balance}"}

            print(f"🚀 Executing MARKET BUY for {symbol} ($ {amount_usdt})")
            
            order = self.exchange.create_order(
                symbol=symbol,
                type='market',
                side='buy',
                amount=None, 
                params={'cost': amount_usdt}
            )
            return order
        except Exception as e:
            print(f"Error executing buy for {symbol}: {e}")
            return {"error": str(e)}

    def execute_market_sell(self, symbol):
        """Execute a market sell order for the entire balance of that coin."""
        if not self.exchange:
            return {"error": "API not configured"}

        try:
            # Fetch balance of the base currency (e.g., BTC if symbol is BTC/USDT)
            base_currency = symbol.split('/')[0].upper()
            balance = self.exchange.fetch_balance()
            amount_to_sell = balance.get(base_currency, {}).get('free', 0)

            if amount_to_sell == 0:
                return {"error": f"No {base_currency} balance to sell."}

            print(f"📉 Executing MARKET SELL for {symbol} (Amount: {amount_to_sell})")
            order = self.exchange.create_order(
                symbol=symbol,
                type='market',
                side='sell',
                amount=amount_to_sell
            )
            return order
        except Exception as e:
            print(f"Error executing sell for {symbol}: {e}")
            return {"error": str(e)}
