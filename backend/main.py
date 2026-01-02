from fastapi import FastAPI, WebSocket, Depends, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
import asyncio
import json
from typing import List, Dict

# Local imports
from database import SessionLocal, engine
import models
from engine import TradingEngine

app = FastAPI(title="AI Trading Platform API")

# Global dictionary to keep track of running engines {user_id: TradingEngine}
active_engines: Dict[int, TradingEngine] = {}

# Enable CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Dependency to get DB session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@app.on_event("startup")
async def startup_event():
    # Initialize DB models
    models.Base.metadata.create_all(bind=engine)
    print("🚀 FastAPI Server Started. Ready for multi-user trading.")

@app.get("/")
async def root():
    return {"status": "online", "message": "AI Trading Platform API v1"}

@app.post("/users/start/{user_id}")
async def start_bot(user_id: int, db: Session = Depends(get_db)):
    """Start a trading bot for a specific user."""
    if user_id in active_engines and active_engines[user_id].is_running:
        return {"message": "Bot already running"}
    
    # Fetch API keys from DB (Mock for now, will use real DB in next step)
    # user_api = db.query(models.ApiKey).filter(models.ApiKey.user_id == user_id).first()
    
    engine_instance = TradingEngine(user_id)
    engine_instance.start()
    active_engines[user_id] = engine_instance
    return {"message": f"Bot started for user {user_id}"}

@app.post("/users/stop/{user_id}")
async def stop_bot(user_id: int):
    """Stop a trading bot for a specific user."""
    if user_id in active_engines:
        active_engines[user_id].stop()
        return {"message": f"Bot stopped for user {user_id}"}
    return {"message": "Bot not running"}

@app.get("/status/{user_id}")
async def get_bot_status(user_id: int):
    """Get the status of a user's bot."""
    is_running = user_id in active_engines and active_engines[user_id].is_running
    return {
        "user_id": user_id,
        "is_running": is_running,
        "active_positions": len(active_engines[user_id].trader.active_positions) if is_running else 0,
        "current_watchlist": active_engines[user_id].watchlist if is_running else []
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
