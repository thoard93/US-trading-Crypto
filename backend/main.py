from fastapi import FastAPI, WebSocket, Depends, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
import asyncio
import json
import time
from typing import List, Dict
from datetime import datetime

# Local imports
from dotenv import load_dotenv
load_dotenv()

from database import SessionLocal, engine
import models
from engine import TradingEngine
from collectors.crypto_collector import CryptoCollector

# Simple manual TTL cache to avoid hitting Kraken too hard and causing timeouts
class SimpleCache:
    def __init__(self, ttl_seconds=15):
        self.cache = {}
        self.ttl = ttl_seconds
    def get(self, key):
        if key in self.cache:
            entry, timestamp = self.cache[key]
            if time.time() - timestamp < self.ttl:
                return entry
        return None
    def set(self, key, value):
        self.cache[key] = (value, time.time())

market_cache = SimpleCache(ttl_seconds=10)
portfolio_cache = SimpleCache(ttl_seconds=15)

app = FastAPI(title="AI Trading Platform API")
crypto_collector = CryptoCollector()

# Global dictionary to keep track of running engines {user_id: TradingEngine}
active_engines: Dict[int, TradingEngine] = {}

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@app.on_event("startup")
async def startup_event():
    models.Base.metadata.create_all(bind=engine)
    print("🚀 FastAPI Server Started.")

@app.get("/")
async def root():
    return {"status": "online"}

@app.post("/users/start/{user_id}")
async def start_bot(user_id: int):
    if user_id in active_engines and active_engines[user_id].is_running:
        return {"message": "Bot already running"}
    
    engine_instance = TradingEngine(user_id)
    engine_instance.start()
    active_engines[user_id] = engine_instance
    return {"message": f"Bot started for user {user_id}"}

@app.post("/users/stop/{user_id}")
async def stop_bot(user_id: int):
    if user_id in active_engines:
        active_engines[user_id].stop()
        return {"message": f"Bot stopped for user {user_id}"}
    return {"message": "Bot not running"}

@app.get("/status/{user_id}")
async def get_bot_status(user_id: int):
    is_running = user_id in active_engines and active_engines[user_id].is_running
    return {
        "user_id": user_id,
        "is_running": is_running,
        "active_positions_count": 0, # Placeholder
        "watchlist": active_engines[user_id].watchlist if is_running else ["BTC/USDT", "ETH/USDT", "SOL/USDT"]
    }

@app.get("/market_data/{user_id}")
async def get_market_data(user_id: int):
    """Fetch current prices and 24h change for the entire watchlist."""
    cached = market_cache.get(f"market_{user_id}")
    if cached: return cached

    is_running = user_id in active_engines and active_engines[user_id].is_running
    watchlist = active_engines[user_id].watchlist if is_running else ["BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT"]
    
    market_data = []
    try:
        tickers = crypto_collector.exchange.fetch_tickers(watchlist)
        for symbol in watchlist:
            if symbol in tickers:
                t = tickers[symbol]
                market_data.append({
                    "symbol": symbol, "price": t['last'],
                    "change": t.get('percentage', 0), "volume": t.get('quoteVolume', 0)
                })
    except Exception as e:
        print(f"⚠️ Market data fetch error: {e}")
        # Fallback to single fetches if needed
        for symbol in watchlist:
            try:
                ticker = crypto_collector.exchange.fetch_ticker(symbol)
                market_data.append({
                    "symbol": symbol, "price": ticker['last'],
                    "change": ticker.get('percentage', 0), "volume": ticker.get('quoteVolume', 0)
                })
            except: continue
    
    market_cache.set(f"market_{user_id}", market_data)
    return market_data

@app.get("/portfolio/{user_id}")
async def get_portfolio(user_id: int):
    """Fetch real-time account balances from Kraken."""
    cached = portfolio_cache.get(f"port_{user_id}")
    if cached: return cached

    try:
        balances = crypto_collector.exchange.fetch_balance()
        assets = []
        # Kraken common keys for USD/USDT
        total_usdt = balances.get('USDT', {}).get('total', 0)
        if total_usdt == 0: total_usdt = balances.get('ZUSD', {}).get('total', 0)
        if total_usdt == 0: total_usdt = balances.get('USD', {}).get('total', 0)
        
        symbol_map = {}
        for currency, data in balances.get('total', {}).items():
            if data > 0 and currency not in ['USDT', 'USD', 'ZUSD', 'EUR', 'ZEUR']:
                clean_currency = currency[1:] if currency.startswith('X') and len(currency) > 3 else currency
                if clean_currency == 'XBT': clean_currency = 'BTC'
                symbol = f"{clean_currency}/USDT"
                symbol_map[symbol] = (clean_currency, data)

        if symbol_map:
            try:
                tickers = crypto_collector.exchange.fetch_tickers(list(symbol_map.keys()))
                for sym, (cur, amt) in symbol_map.items():
                    if sym in tickers:
                        price = tickers[sym]['last']
                        assets.append({"asset": cur, "amount": amt, "price": price, "value_usdt": amt * price})
            except Exception as e:
                print(f"⚠️ Portfolio batch fetch failed: {e}")
                for sym, (cur, amt) in symbol_map.items():
                    try:
                        price = crypto_collector.exchange.fetch_ticker(sym)['last']
                        assets.append({"asset": cur, "amount": amt, "price": price, "value_usdt": amt * price})
                    except: continue
                    
        result = {"usdt_balance": total_usdt, "assets": sorted(assets, key=lambda x: x['value_usdt'], reverse=True)}
        portfolio_cache.set(f"port_{user_id}", result)
        return result
    except Exception as e:
        print(f"❌ Portfolio fetch error: {e}")
        return {"usdt_balance": 0, "assets": []}

@app.get("/positions/{user_id}")
async def get_positions(user_id: int):
    """Retrieve active trading positions."""
    is_running = user_id in active_engines and active_engines[user_id].is_running
    
    pos_data = []
    symbol_targets = {} # symbol -> {entry_price, side}

    # 1. Collect from running engine
    if is_running:
        for symbol, data in active_engines[user_id].trader.active_positions.items():
            symbol_targets[symbol] = {"entry": data['entry_price'], "side": "BUY"}
    
    # 2. Collect from database
    db = SessionLocal()
    try:
        db_positions = db.query(models.Position).filter(models.Position.user_id == user_id).all()
        for db_pos in db_positions:
            if db_pos.symbol not in symbol_targets:
                symbol_targets[db_pos.symbol] = {"entry": db_pos.entry_price, "side": "BUY"}
    finally:
        db.close()

    # 3. Batch fetch all prices at once
    if symbol_targets:
        try:
            tickers = crypto_collector.exchange.fetch_tickers(list(symbol_targets.keys()))
            for symbol, info in symbol_targets.items():
                if symbol in tickers:
                    current_price = tickers[symbol]['last']
                    entry_price = info['entry']
                    profit_pct = ((current_price - entry_price) / entry_price) * 100
                    pos_data.append({
                        "symbol": symbol,
                        "entry": round(entry_price, 8),
                        "current": round(current_price, 8),
                        "profit": f"{'+' if profit_pct >= 0 else ''}{round(profit_pct, 2)}%",
                        "side": info['side']
                    })
        except Exception as e:
            print(f"⚠️ Positions batch fetch failed: {e}")
            # Minimum fallback (slow but safe)
            for symbol, info in symbol_targets.items():
                try:
                    current_price = crypto_collector.exchange.fetch_ticker(symbol)['last']
                    profit_pct = ((current_price - info['entry']) / info['entry']) * 100
                    pos_data.append({
                        "symbol": symbol,
                        "entry": round(info['entry'], 8),
                        "current": round(current_price, 8),
                        "profit": f"{'+' if profit_pct >= 0 else ''}{round(profit_pct, 2)}%",
                        "side": info['side']
                    })
                except: continue

    if pos_data:
        return pos_data
    else:
        # Fallback: holdings (already cached)
        p = await get_portfolio(user_id)
        return [{
            "symbol": f"{a['asset']}/USDT",
            "entry": a['price'],
            "current": a['price'],
            "profit": "---",
            "side": "HOLD"
        } for a in p['assets'][:5]]

@app.get("/trades/{user_id}")
async def get_trades(user_id: int, db: Session = Depends(get_db)):
    """Retrieve execution history from DB with Kraken fetch fallback."""
    trades = db.query(models.Trade).filter(models.Trade.user_id == user_id).order_by(models.Trade.timestamp.desc()).limit(20).all()
    
    formatted = [{
        "type": t.type if hasattr(t, 'type') else "TRADE",
        "symbol": t.symbol,
        "price": round(t.price, 8),
        "time": t.timestamp.strftime("%Y-%m-%d %H:%M:%S")
    } for t in trades]

    if not formatted and crypto_collector.exchange.apiKey:
        try:
            kraken_trades = crypto_collector.exchange.fetch_my_trades(limit=10)
            for kt in kraken_trades:
                formatted.append({
                    "type": kt['side'].upper(),
                    "symbol": kt['symbol'],
                    "price": kt['price'],
                    "time": datetime.fromtimestamp(kt['timestamp']/1000).strftime("%Y-%m-%d %H:%M:%S")
                })
        except: pass
        
    return formatted

@app.get("/chart/{symbol:path}")
async def get_chart_data(symbol: str, timeframe: str = '5m'):
    if "%2F" in symbol:
        symbol = symbol.replace("%2f", "/").replace("%2F", "/")
    
    data = crypto_collector.fetch_ohlcv(symbol, timeframe=timeframe, limit=50)
    if data is None or data.empty:
        raise HTTPException(status_code=404, detail="Symbol not found or no data")
    
    chart_data = []
    for index, row in data.iterrows():
        time_format = "%H:%M" if timeframe in ['1m', '5m', '15m'] else "%d %H:%M"
        if timeframe == '1d': time_format = "%m/%d"
        chart_data.append({"time": row['timestamp'].strftime(time_format), "price": row['close']})
    return chart_data

@app.get("/stats/{user_id}")
async def get_stats(user_id: int, db: Session = Depends(get_db)):
    trades = db.query(models.Trade).filter(models.Trade.user_id == user_id).all()
    total_profit = sum([float(t.cost) for t in trades if t.side == 'SELL']) - sum([float(t.cost) for t in trades if t.side == 'BUY']) if trades else 0
    
    is_running = user_id in active_engines and active_engines[user_id].is_running
    return {
        "total_profit": f"${round(total_profit, 2)}",
        "active_bots_count": 1 if is_running else 0,
        "active_bot_names": "US Automated Scalper" if is_running else "None"
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
