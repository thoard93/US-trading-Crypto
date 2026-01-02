import asyncio
from typing import Dict, List
from collectors.crypto_collector import CryptoCollector
from analysis.technical_engine import TechnicalAnalysis
from trading_executive import TradingExecutive
from analysis.safety_checker import SafetyChecker

class TradingEngine:
    """A standalone trading bot instance for a specific user."""
    def __init__(self, user_id: int, api_key: str = None, api_secret: str = None):
        self.user_id = user_id
        self.crypto = CryptoCollector()
        self.analyzer = TechnicalAnalysis()
        self.trader = TradingExecutive(api_key, api_secret)
        self.safety = SafetyChecker()
        
        self.watchlist = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'XRP/USDT']
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
                                self.trader.execute_market_sell(symbol)
                        
                        # 2. Check Signals
                        if result.get('signal') == 'BUY':
                            if symbol not in self.trader.active_positions:
                                # Execute buy
                                buy_res = self.trader.execute_market_buy(symbol, amount_usdt=10.0)
                                if "error" not in buy_res:
                                    self.trader.track_position(symbol, current_price, buy_res.get('amount', 0))

                    await asyncio.sleep(1) # Gap between symbols
                    
                await asyncio.sleep(300) # 5-minute cycle
            except Exception as e:
                print(f"❌ Engine error for user {self.user_id}: {e}")
                await asyncio.sleep(30)

    def start(self):
        if not self.is_running:
            self._task = asyncio.create_task(self.run_loop())

    def stop(self):
        self.is_running = False
        if self._task:
            self._task.cancel()
