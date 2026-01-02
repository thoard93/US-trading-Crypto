import asyncio
from typing import Dict, List
from collectors.crypto_collector import CryptoCollector
from analysis.technical_engine import TechnicalAnalysis
from trading_executive import TradingExecutive
from analysis.safety_checker import SafetyChecker
from database import SessionLocal
import models
import datetime

class TradingEngine:
    """A standalone trading bot instance for a specific user."""
    def __init__(self, user_id: int, api_key: str = None, api_secret: str = None):
        self.user_id = user_id
        # If keys are provided, they are likely already decrypted.
        # If not, TradingExecutive will check env as fallback.
        self.trader = TradingExecutive(api_key, api_secret, user_id=user_id)
        self.crypto = self.trader.crypto # Share the same ccxt instance
        self.analyzer = TechnicalAnalysis()
        self.safety = SafetyChecker()
        
        self.watchlist = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'XRP/USDT', 'PEPE/USDT']
        self.is_running = False
        self._task = None

    async def run_loop(self):
        self.is_running = True
        print(f"🚀 Bot starting for user {self.user_id}")
        
        # Initial position sync
        self.trader.sync_positions()
        
        while self.is_running:
            try:
                for symbol in self.watchlist:
                    # Fetch 5m data for scalping
                    data = self.crypto.fetch_ohlcv(symbol, timeframe='5m', limit=100)
                    if data is not None and not data.empty:
                        current_price = data.iloc[-1]['close']
                        result = self.analyzer.analyze_trend(data)
                        
                        # 1. Check Portfolio Exits
                        if symbol in self.trader.active_positions:
                            exit_reason = self.trader.check_exit_conditions(symbol, current_price)
                            if exit_reason:
                                sell_res = self.trader.execute_market_sell(symbol)
                                if "error" not in sell_res:
                                    self._record_trade(symbol, "SELL", sell_res.get('amount', 0), current_price)
                        
                        # 2. Check Signals
                        if result.get('signal') == 'BUY':
                            if symbol not in self.trader.active_positions:
                                # Execute buy
                                buy_res = self.trader.execute_market_buy(symbol, amount_usdt=10.0)
                                if "error" not in buy_res:
                                    self.trader.track_position(symbol, current_price, buy_res.get('amount', 0))
                                    self._record_trade(symbol, "BUY", buy_res.get('amount', 0), current_price)

                    await asyncio.sleep(1) # Gap between symbols
                    
                await asyncio.sleep(60) # Increased frequency for more active feel
            except Exception as e:
                print(f"❌ Engine error for user {self.user_id}: {e}")
                await asyncio.sleep(30)

    def _record_trade(self, symbol, side, amount, price):
        """Record trade to database."""
        db = SessionLocal()
        try:
            trade = models.Trade(
                symbol=symbol,
                side=side,
                amount=float(amount),
                price=float(price),
                cost=float(amount * price),
                user_id=self.user_id,
                timestamp=datetime.datetime.utcnow()
            )
            db.add(trade)
            db.commit()
            print(f"📝 Recorded {side} trade for {symbol}")
        except Exception as e:
            print(f"❌ Error recording trade: {e}")
        finally:
            db.close()

    def start(self):
        if not self.is_running:
            self._task = asyncio.create_task(self.run_loop())

    def stop(self):
        self.is_running = False
        if self._task:
            self._task.cancel()
