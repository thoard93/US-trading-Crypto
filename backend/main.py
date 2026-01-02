from fastapi import FastAPI, WebSocket, Depends, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
import asyncio
import json
from typing import List, Dict
from datetime import datetime, timedelta

# Local imports
from database import SessionLocal, engine
import models
from engine import TradingEngine
from collectors.crypto_collector import CryptoCollector

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

@app.get("/portfolio/{user_id}")
async def get_portfolio(user_id: int):
    """Fetch real-time account balances from Kraken."""
    try:
        # Kraken balance fetch
        balances = crypto_collector.exchange.fetch_balance()
        total_usdt = balances.get('USDT', {}).get('total', 0)
        
        assets = []
        for currency, data in balances['total'].items():
            if data > 0 and currency not in ['USDT', 'USD', 'EUR']:
                # Get current price
                try:
                    symbol = f"{currency}/USDT"
                    ticker = crypto_collector.exchange.fetch_ticker(symbol)
                    price = ticker['last']
                    assets.append({
                        "asset": currency,
                        "amount": data,
                        "price": price,
                        "value_usdt": data * price
                    })
                except:
                    continue
                    
        return {
            "usdt_balance": total_usdt,
            "assets": sorted(assets, key=lambda x: x['value_usdt'], reverse=True)
        }
    except Exception as e:
        print(f"Portfolio fetch error: {e}")
        return {"usdt_balance": 0, "assets": []}

@app.get("/positions/{user_id}")
async def get_positions(user_id: int):
    """Retrieve active trading positions."""
    is_running = user_id in active_engines and active_engines[user_id].is_running
    
    # If bot is running, get tracked positions. Otherwise, return raw Kraken assets.
    if is_running:
        pos_data = []
        for symbol, data in active_engines[user_id].trader.active_positions.items():
            try:
                ticker = crypto_collector.exchange.fetch_ticker(symbol)
                current_price = ticker['last']
                entry_price = data['entry_price']
                profit_pct = ((current_price - entry_price) / entry_price) * 100
                
                pos_data.append({
                    "symbol": symbol,
                    "entry": round(entry_price, 8),
                    "current": round(current_price, 8),
                    "profit": f"{'+' if profit_pct >= 0 else ''}{round(profit_pct, 2)}%",
                    "side": "BUY"
                })
            except: continue
        return pos_data
    else:
        # Return summary of assets from Portfolio logic
        portfolio = await get_portfolio(user_id)
        return [{
            "symbol": f"{a['asset']}/USDT",
            "entry": 0, # Entry unknown when idle
            "current": a['price'],
            "profit": "---",
            "side": "HOLD"
        } for a in portfolio['assets'][:5]] # Show top 5

@app.get("/trades/{user_id}")
async def get_trades(user_id: int, db: Session = Depends(get_db)):
    trades = db.query(models.Trade).filter(models.Trade.user_id == user_id).order_by(models.Trade.timestamp.desc()).limit(10).all()
    return [{
        "type": t.side,
        "symbol": t.symbol,
        "price": round(t.price, 8),
        "time": t.timestamp.strftime("%H:%M:%S")
    } for t in trades]

@app.get("/chart/{symbol:path}")
async def get_chart_data(symbol: str):
    # Sanitize symbol (FastAPI might escape the /)
    if "%2F" in symbol:
        symbol = symbol.replace("%2f", "/").replace("%2F", "/")
    
    data = crypto_collector.fetch_ohlcv(symbol, timeframe='5m', limit=50)
    if data is None or data.empty:
        raise HTTPException(status_code=404, detail="Symbol not found or no data")
    
    chart_data = []
    for index, row in data.iterrows():
        chart_data.append({
            "time": row['timestamp'].strftime("%H:%M"),
            "price": row['close']
        })
    return chart_data

@app.get("/stats/{user_id}")
async def get_stats(user_id: int, db: Session = Depends(get_db)):
    # Calculate simple stats from DB
    trades = db.query(models.Trade).filter(models.Trade.user_id == user_id).all()
    total_profit = sum([t.cost for t in trades if t.side == 'SELL']) - sum([t.cost for t in trades if t.side == 'BUY'])
    
    is_running = user_id in active_engines and active_engines[user_id].is_running
    active_bot_count = 1 if is_running else 0
    
    return {
        "total_profit": f"${round(total_profit, 2)}",
        "active_bots_count": active_bot_count,
        "active_bot_names": "US Automated Scalper" if is_running else "None"
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
