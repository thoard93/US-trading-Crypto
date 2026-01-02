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
from cryptography.fernet import Fernet
from encryption_utils import encrypt_key, decrypt_key
from auth_utils import get_discord_auth_url, get_discord_token, get_discord_user
from jose import jwt

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

# --- AUTH ROUTES ---
@app.get("/auth/discord/url")
async def discord_url():
    return {"url": get_discord_auth_url()}

@app.get("/auth/discord/callback")
async def discord_callback(code: str, db: Session = Depends(get_db)):
    token_data = get_discord_token(code)
    if "access_token" not in token_data:
        error_msg = token_data.get("error_description", token_data.get("error", "Unknown error"))
        print(f"❌ Discord Auth Error: {error_msg}")
        raise HTTPException(status_code=400, detail=f"Discord Error: {error_msg}")
    
    user_info = get_discord_user(token_data["access_token"])
    discord_id = str(user_info["id"])
    
    user = db.query(models.User).filter(models.User.discord_id == discord_id).first()
    if not user:
        user = models.User(
            username=user_info["username"],
            discord_id=discord_id,
            avatar=f"https://cdn.discordapp.com/avatars/{discord_id}/{user_info['avatar']}.png"
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    
    # Generate JWT
    payload = {"user_id": user.id, "exp": time.time() + 86400}
    token = jwt.encode(payload, os.getenv("SECRET_KEY", "fallback_secret"), algorithm="HS256")
    return {"token": token, "user": {"id": user.id, "username": user.username, "avatar": user.avatar}}

# --- API KEY MANAGEMENT ---
@app.post("/settings/keys")
async def save_api_keys(user_id: int, exchange: str, api_key: str, api_secret: str, db: Session = Depends(get_db)):
    # Encrypt keys before saving
    encrypted_key = encrypt_key(api_key)
    encrypted_secret = encrypt_key(api_secret)
    
    existing = db.query(models.ApiKey).filter(models.ApiKey.user_id == user_id, models.ApiKey.exchange == exchange).first()
    if existing:
        existing.api_key = encrypted_key
        existing.api_secret = encrypted_secret
    else:
        new_key = models.ApiKey(
            exchange=exchange,
            api_key=encrypted_key,
            api_secret=encrypted_secret,
            user_id=user_id
        )
        db.add(new_key)
    
    db.commit()
    return {"message": "API keys saved and encrypted"}

@app.post("/users/start/{user_id}")
async def start_bot(user_id: int, db: Session = Depends(get_db)):
    if user_id in active_engines and active_engines[user_id].is_running:
        return {"message": "Bot already running"}
    
    # 1. Fetch Kraken Keys
    kraken_entry = db.query(models.ApiKey).filter(models.ApiKey.user_id == user_id, models.ApiKey.exchange == 'kraken').first()
    api_key, api_secret = None, None
    if kraken_entry:
        api_key = decrypt_key(kraken_entry.api_key)
        api_secret = decrypt_key(kraken_entry.api_secret)
        print(f"🔑 Loaded Kraken keys for user {user_id}")

    # 2. Fetch Alpaca Keys
    alpaca_entry = db.query(models.ApiKey).filter(models.ApiKey.user_id == user_id, models.ApiKey.exchange == 'alpaca').first()
    alp_key, alp_secret = None, None
    if alpaca_entry:
        alp_key = decrypt_key(alpaca_entry.api_key)
        alp_secret = decrypt_key(alpaca_entry.api_secret)
        print(f"🔑 Loaded Alpaca keys for user {user_id}")

    engine_instance = TradingEngine(
        user_id, 
        api_key=api_key, api_secret=api_secret,
        alpaca_key=alp_key, alpaca_secret=alp_secret
    )
    engine_instance.start()
    active_engines[user_id] = engine_instance
    return {"message": f"Bot started for user {user_id}"}

@app.post("/users/stop/{user_id}")
async def stop_bot(user_id: int):
    if user_id in active_engines:
        active_engines[user_id].stop()
        del active_engines[user_id] # Clean up
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
    """Fetch current prices for both crypto and stock watchlists."""
    cached = market_cache.get(f"market_{user_id}")
    if cached: return cached

    engine = active_engines.get(user_id)
    watchlist = engine.watchlist if engine else ["BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT"]
    stock_watchlist = engine.stock_watchlist if engine else ["TSLA", "NVDA", "AAPL", "AMD"]
    
    market_data = []
    
    # 1. Crypto Prices
    try:
        k_ex = engine.trader.exchange if engine else crypto_collector.exchange
        tickers = k_ex.fetch_tickers(watchlist)
        for symbol in watchlist:
            if symbol in tickers:
                t = tickers[symbol]
                market_data.append({
                    "symbol": symbol, "price": t['last'],
                    "change": t.get('percentage', 0), "volume": t.get('quoteVolume', 0),
                    "type": "CRYPTO"
                })
    except Exception as e:
        print(f"⚠️ Market crypto error: {e}")

    # 2. Stock Prices
    s_coll = engine.stock_collector if engine else None
    if s_coll:
        for symbol in stock_watchlist:
            try:
                price = s_coll.get_current_price(symbol)
                if price:
                    market_data.append({
                        "symbol": symbol, "price": price,
                        "change": 0.0, "volume": 0.0, # Alpaca free tier change data is limited
                        "type": "STOCK"
                    })
            except: continue
    
    market_cache.set(f"market_{user_id}", market_data)
    return market_data

@app.get("/portfolio/{user_id}")
async def get_portfolio(user_id: int):
    """Fetch real-time account balances from Kraken and Alpaca."""
    cached = portfolio_cache.get(f"port_{user_id}")
    if cached: return cached

    assets = []
    total_usdt = 0.0
    
    # helper to get collectors
    engine = active_engines.get(user_id)
    k_ex = engine.trader.exchange if engine else crypto_collector.exchange
    s_api = engine.trader.stock_api if engine else None
    
    # 1. Kraken Crypto Fetch
    try:
        balances = k_ex.fetch_balance()
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
                tickers = k_ex.fetch_tickers(list(symbol_map.keys()))
                for sym, (cur, amt) in symbol_map.items():
                    if sym in tickers:
                        price = tickers[sym]['last']
                        assets.append({"asset": cur, "amount": amt, "price": price, "value_usdt": amt * price, "type": "CRYPTO"})
            except:
                for sym, (cur, amt) in symbol_map.items():
                    try:
                        price = k_ex.fetch_ticker(sym)['last']
                        assets.append({"asset": cur, "amount": amt, "price": price, "value_usdt": amt * price, "type": "CRYPTO"})
                    except: continue
    except Exception as e:
        print(f"⚠️ Kraken portfolio error: {e}")

    # 2. Alpaca Stock Fetch
    if s_api:
        try:
            alp_pos = s_api.list_positions()
            for pos in alp_pos:
                assets.append({
                    "asset": pos.symbol,
                    "amount": float(pos.qty),
                    "price": float(pos.current_price),
                    "value_usdt": float(pos.market_value),
                    "type": "STOCK"
                })
            
            # Also get buying power (cash)
            account = s_api.get_account()
            total_usdt += float(account.cash)
        except Exception as e:
            print(f"⚠️ Alpaca portfolio error: {e}")

    result = {"usdt_balance": total_usdt, "assets": sorted(assets, key=lambda x: x['value_usdt'], reverse=True)}
    portfolio_cache.set(f"port_{user_id}", result)
    return result

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

    # 3. Fetch Prices
    if symbol_targets:
        engine = active_engines.get(user_id)
        k_ex = engine.trader.exchange if engine else crypto_collector.exchange
        s_coll = engine.stock_collector if engine else None # StockCollector from engine
        
        crypto_symbols = [s for s in symbol_targets.keys() if '/' in s]
        stock_symbols = [s for s in symbol_targets.keys() if '/' not in s]
        
        # --- 3a. Crypto Prices ---
        if crypto_symbols:
            try:
                tickers = k_ex.fetch_tickers(crypto_symbols)
                for symbol in crypto_symbols:
                    if symbol in tickers:
                        current_price = tickers[symbol]['last']
                        entry_price = symbol_targets[symbol]['entry']
                        profit_pct = ((current_price - entry_price) / entry_price) * 100
                        pos_data.append({
                            "symbol": symbol, "entry": round(entry_price, 8),
                            "current": round(current_price, 8),
                            "profit": f"{'+' if profit_pct >= 0 else ''}{round(profit_pct, 2)}%",
                            "side": symbol_targets[symbol]['side'], "type": "CRYPTO"
                        })
            except Exception as e: print(f"⚠️ Crypto pos price error: {e}")

        # --- 3b. Stock Prices ---
        if stock_symbols and s_coll:
            for symbol in stock_symbols:
                try:
                    price = s_coll.get_current_price(symbol)
                    if price:
                        entry = symbol_targets[symbol]['entry']
                        profit_pct = ((price - entry) / entry) * 100
                        pos_data.append({
                            "symbol": symbol, "entry": round(entry, 2),
                            "current": round(price, 2),
                            "profit": f"{'+' if profit_pct >= 0 else ''}{round(profit_pct, 2)}%",
                            "side": symbol_targets[symbol]['side'], "type": "STOCK"
                        })
                except Exception as e: print(f"⚠️ Stock pos price error: {e}")

    return pos_data if pos_data else []

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
    
    # Try to find a collector
    # In a real multi-user system, we'd need the user_id here too
    # For now, we'll try the first active engine or the global crypto collector
    engine = None
    if active_engines:
        engine = list(active_engines.values())[0]
        
    data = None
    if '/' in symbol:
        coll = engine.crypto if engine else crypto_collector
        data = coll.fetch_ohlcv(symbol, timeframe=timeframe, limit=50)
    else:
        # Stocks
        # Map timeframe
        tf_map = {'1m': '1Min', '5m': '5Min', '15m': '15Min', '1h': '1Hour', '1d': '1Day'}
        tf = tf_map.get(timeframe, '1Hour')
        
        from collectors.stock_collector import StockCollector
        s_coll = engine.stock_collector if engine else StockCollector()
        data = s_coll.fetch_ohlcv(symbol, timeframe=tf, limit=50)

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
