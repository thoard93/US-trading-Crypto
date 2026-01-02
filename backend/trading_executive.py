import ccxt
import os
import logging

class TradingExecutive:
    def __init__(self, api_key=None, secret_key=None, alpaca_key=None, alpaca_secret=None, alpaca_url=None, user_id=1):
        self.api_key = api_key or os.getenv('KRAKEN_API_KEY')
        self.secret_key = secret_key or os.getenv('KRAKEN_SECRET_KEY')
        self.alpaca_key = alpaca_key or os.getenv('ALPACA_API_KEY')
        self.alpaca_secret = alpaca_secret or os.getenv('ALPACA_SECRET_KEY')
        self.alpaca_url = alpaca_url or os.getenv('ALPACA_BASE_URL')
        self.user_id = user_id
        
        # Initialize CryptoCollector with specific keys
        from collectors.crypto_collector import CryptoCollector
        self.crypto = CryptoCollector(api_key=self.api_key, api_secret=self.secret_key)
        self.exchange = self.crypto.exchange
        
        # Initialize StockCollector with specific keys
        from collectors.stock_collector import StockCollector
        self.stock_collector = StockCollector(api_key=self.alpaca_key, secret_key=self.alpaca_secret, base_url=self.alpaca_url)
        self.stock_api = self.stock_collector.api
        
        if self.exchange and self.exchange.apiKey:
            print(f"✅ Crypto Trading initialized for user {self.user_id}.")
        
        if self.stock_api:
            print(f"✅ Stock Trading (Alpaca) initialized for user {self.user_id}.")
        else:
            print(f"⚠️ Stock Trading disabled for user {self.user_id} (No keys).")

        # Scalp-optimized Safety Settings
        self.trade_amount_usdt = 10.0  
        self.max_open_trades = 5      
        self.active_positions = {}    # {symbol: {"entry_price": float, "amount": float}}
        
        # Load existing positions from DB
        self.load_positions_from_db()

    def load_positions_from_db(self):
        """Restore active positions from the database."""
        from database import SessionLocal
        import models
        db = SessionLocal()
        try:
            db_positions = db.query(models.Position).filter(models.Position.user_id == self.user_id).all()
            for pos in db_positions:
                self.active_positions[pos.symbol] = {
                    "entry_price": pos.entry_price,
                    "amount": pos.amount
                }
            print(f"🧠 Recovered {len(db_positions)} positions from database memory.")
        except Exception as e:
            print(f"❌ Failed to load positions from DB: {e}")
        finally:
            db.close()

    def track_position(self, symbol, entry_price, amount):
        """Record an entry for stop-loss monitoring and persist to DB."""
        # Validate inputs before tracking
        if entry_price is None or amount is None:
            print(f"⚠️ Cannot track {symbol}: entry_price={entry_price}, amount={amount}")
            return
            
        self.active_positions[symbol] = {
            "entry_price": float(entry_price),
            "amount": float(amount)
        }
        
        from database import SessionLocal
        import models
        db = SessionLocal()
        try:
            # Check if exists to avoid duplicates
            existing = db.query(models.Position).filter(
                models.Position.user_id == self.user_id,
                models.Position.symbol == symbol
            ).first()
            
            if not existing:
                db_pos = models.Position(
                    symbol=symbol,
                    entry_price=float(entry_price),
                    amount=float(amount),
                    user_id=self.user_id
                )
                db.add(db_pos)
                db.commit()
                print(f"💾 Persisted {symbol} position to DB.")
        except Exception as e:
            print(f"❌ Error persisting position: {e}")
        finally:
            db.close()

    def check_exit_conditions(self, symbol, current_price):
        """Check if we should exit a trade based on SL/TP."""
        if symbol not in self.active_positions:
            return None

        pos = self.active_positions[symbol]
        entry = pos["entry_price"]
        
        # Aggressive Scalp Stop-Loss: -2% (Reduced from 5%)
        if current_price <= entry * 0.98:
            return "STOP_LOSS"
        
        # Aggressive Scalp Take-Profit: +3% (Reduced from 10% for faster cycles)
        if current_price >= entry * 1.03:
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
            # Remove from local active positions
            if symbol in self.active_positions:
                del self.active_positions[symbol]
                
            # Remove from database
            from database import SessionLocal
            import models
            db = SessionLocal()
            try:
                db.query(models.Position).filter(
                    models.Position.user_id == self.user_id,
                    models.Position.symbol == symbol
                ).delete()
                db.commit()
                print(f"🗑️ Removed {symbol} position from DB memory.")
            except Exception as e:
                print(f"❌ Error deleting position from DB: {e}")
            finally:
                db.close()
                
            return order
        except Exception as e:
            print(f"Error executing sell for {symbol}: {e}")
            return {"error": str(e)}

    def execute_market_buy_stock(self, symbol, notional=5.0, qty=None):
        """Execute a market buy order for a stock using fractional shares."""
        if not self.stock_api:
            return {"error": "Alpaca API not configured"}
        try:
            # Use notional (dollar amount) for fractional share purchases
            if notional and not qty:
                print(f"🚀 Executing ALPACA MARKET BUY for {symbol} (${notional})")
                order = self.stock_api.submit_order(
                    symbol=symbol,
                    notional=notional,
                    side='buy',
                    type='market',
                    time_in_force='day'
                )
            else:
                print(f"🚀 Executing ALPACA MARKET BUY for {symbol} (Qty: {qty})")
                order = self.stock_api.submit_order(
                    symbol=symbol,
                    qty=qty,
                    side='buy',
                    type='market',
                    time_in_force='day'
                )
            
            return {
                "success": True,
                "id": order.id,
                "symbol": symbol,
                "side": "buy",
                "notional": notional,
                "amount": notional  # For tracking
            }
        except Exception as e:
            print(f"Error executing stock buy for {symbol}: {e}")
            return {"error": str(e)}

    def execute_market_sell_stock(self, symbol, percentage=100):
        """Execute a market sell order for a stock position (supports fractional)."""
        if not self.stock_api:
            return {"error": "Alpaca API not configured"}
        try:
            if percentage == 100:
                print(f"📉 Executing ALPACA CLOSE POSITION for {symbol}")
                # close_position automatically liquidates the full amount
                order = self.stock_api.close_position(symbol)
                # Note: close_position returns a different object (Order) or just the order details
                # It avoids precision errors with fractional shares
            else:
                # Partial sell logic
                pos = self.stock_api.get_position(symbol)
                qty = float(pos.qty)
                qty_to_sell = qty * (percentage / 100)
                
                print(f"📉 Executing ALPACA MARKET SELL for {symbol} (Qty: {qty_to_sell})")
                order = self.stock_api.submit_order(
                    symbol=symbol,
                    qty=qty_to_sell,
                    side='sell',
                    type='market',
                    time_in_force='day'
                )
            
            # Remove from positions if full sell
            if percentage == 100 and symbol in self.active_positions:
                del self.active_positions[symbol]
            
            return {
                "success": True,
                "id": order.id,
                "symbol": symbol,
                "side": "sell",
                "qty": qty
            }
        except Exception as e:
            print(f"Error executing stock sell for {symbol}: {e}")
            return {"error": str(e)}

    def sync_positions(self):
        """Fetch current holdings from Kraken and Alpaca."""
        # --- 1. Kraken Sync ---
        if self.exchange:
            print("🔄 Syncing live holdings from Kraken...")
            try:
                balance = self.exchange.fetch_balance()
                total_bals = balance.get('total', {})
                for asset, total_amount in total_bals.items():
                    if asset in ['USDT', 'USD', 'ZUSD', 'EUR', 'CAD']: continue
                    if total_amount > 0:
                        symbol = f"{asset}/USDT"
                        try:
                            if symbol not in self.exchange.markets: self.exchange.load_markets()
                            if symbol not in self.exchange.markets:
                                alt_symbol = f"X{asset}/USDT"
                                if alt_symbol in self.exchange.markets: symbol = alt_symbol
                                else: continue
                            ticker = self.exchange.fetch_ticker(symbol)
                            price = ticker['last']
                            if total_amount * price > 5.0:
                                self.track_position(symbol, price, total_amount)
                                print(f"✅ Adopting Kraken: {symbol}")
                        except: continue
            except Exception as e: print(f"❌ Kraken sync error: {e}")

        # --- 2. Alpaca Sync ---
        if self.stock_api:
            print("🔄 Syncing live holdings from Alpaca...")
            try:
                alp_positions = self.stock_api.list_positions()
                for pos in alp_positions:
                    symbol = pos.symbol
                    price = float(pos.current_price)
                    qty = float(pos.qty)
                    self.track_position(symbol, price, qty)
                    print(f"✅ Adopting Alpaca: {symbol}")
            except Exception as e: print(f"❌ Alpaca sync error: {e}")
