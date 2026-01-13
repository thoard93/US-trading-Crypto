import os
import logging
import time
from fastapi import FastAPI, Request, HTTPException, BackgroundTasks, Depends
from pydantic import BaseModel
from typing import List, Optional, Dict
from sqlalchemy.orm import Session

# Setup Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("WebhookListener")

# SILENCE Uvicorn Access Logs (They spam every single transaction)
class NoWebhookFilter(logging.Filter):
    def filter(self, record):
        # Silence standard uvicorn access logs for the webhook endpoint
        return "POST /helius/webhook" not in record.getMessage()

logging.getLogger("uvicorn.access").addFilter(NoWebhookFilter())
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
logging.getLogger("uvicorn.error").setLevel(logging.WARNING)

from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="DEGEN DEX API + Webhook Listener")

# CORS - Allow frontend to connect
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global reference to the bot/cog - will be set during bot startup
bot_instance = None

# Simple cache for API responses
class SimpleCache:
    def __init__(self, ttl_seconds=10):
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

api_cache = SimpleCache(ttl_seconds=10)

# Database dependency
def get_db():
    from database import SessionLocal
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def get_alert_system():
    """Helper to get AlertSystem from bot instance."""
    if not bot_instance:
        return None
    return bot_instance.get_cog("AlertSystem")

# ============================================
# DEX-FOCUSED API ENDPOINTS (Override Kraken)
# ============================================

@app.get("/")
async def health_check():
    alert_sys = get_alert_system()
    whale_count = 0
    if alert_sys and hasattr(alert_sys, 'copy_trader'):
        whale_count = len(getattr(alert_sys.copy_trader, 'qualified_wallets', []))
    return {
        "status": "alive", 
        "bot_connected": bot_instance is not None,
        "whales_tracked": whale_count // 2  # Divided by 2 since it stores both address types
    }

@app.get("/status/{user_id}")
async def get_bot_status(user_id: int):
    """Get DEX bot status - shows whale tracking info."""
    alert_sys = get_alert_system()
    is_running = alert_sys is not None and getattr(alert_sys, 'ready', False)
    
    whale_count = 0
    swarm_signals = 0
    if alert_sys:
        if hasattr(alert_sys, 'copy_trader'):
            whale_count = len(getattr(alert_sys.copy_trader, 'qualified_wallets', [])) // 2
            swarm_signals = len(getattr(alert_sys.copy_trader, 'activity_cache', {}))
    
    return {
        "user_id": user_id,
        "is_running": is_running,
        "whales_tracked": whale_count,
        "active_swarms": swarm_signals,
        "watchlist": ["🐋 Whale Hunting Active"] if is_running else ["🔌 Connecting..."]
    }

@app.get("/market_data/{user_id}")
async def get_market_data(user_id: int):
    """Get whale swarm activity instead of Kraken prices."""
    cached = api_cache.get(f"market_{user_id}")
    if cached: return cached
    
    alert_sys = get_alert_system()
    market_data = []
    
    if alert_sys and hasattr(alert_sys, 'copy_trader'):
        copy_trader = alert_sys.copy_trader
        
        # Get top swarm signals
        top_tokens = copy_trader.get_top_signals(limit=6) if hasattr(copy_trader, 'get_top_signals') else []
        
        for token_info in top_tokens:
            market_data.append({
                "symbol": token_info.get('symbol', token_info.get('mint', 'Unknown')[:8] + '...'),
                "price": token_info.get('price', 0),
                "change": token_info.get('whale_count', 0),  # Use whale count as "change"
                "volume": token_info.get('liquidity', 0),
                "type": "SWARM"
            })
    
    # Fallback if no swarm data
    if not market_data:
        market_data = [
            {"symbol": "🐋 Tracking...", "price": 0, "change": 0, "volume": 0, "type": "SWARM"},
        ]
    
    api_cache.set(f"market_{user_id}", market_data)
    return market_data

@app.get("/portfolio/{user_id}")
async def get_portfolio(user_id: int, db: Session = Depends(get_db)):
    """Get user's Solana wallet tokens (not Kraken)."""
    cached = api_cache.get(f"port_{user_id}")
    if cached: return cached
    
    assets = []
    total_sol = 0.0
    
    alert_sys = get_alert_system()
    trader = None
    
    # 1. First check AlertSystem for existing trader
    if alert_sys and hasattr(alert_sys, 'dex_traders'):
        for t in alert_sys.dex_traders:
            trader_user_id = getattr(t, 'user_id', 1)
            if trader_user_id == user_id or user_id == 1:
                trader = t
                break
    
    # 2. If no trader found, try to create one from user's saved key
    if not trader:
        try:
            import models
            from encryption_utils import decrypt_key
            from dex_trader import DexTrader
            
            key_entry = db.query(models.ApiKey).filter(
                models.ApiKey.user_id == user_id,
                models.ApiKey.exchange == 'solana'
            ).first()
            
            if key_entry:
                private_key = decrypt_key(key_entry.api_key)
                trader = DexTrader(private_key=private_key)
                trader.user_id = user_id
                logger.info(f"🔑 Created temp DexTrader for user {user_id}")
        except Exception as e:
            logger.error(f"Error creating DexTrader for user {user_id}: {e}")
    
    # 3. Fetch portfolio from trader
    if trader:
        try:
            total_sol = trader.get_sol_balance() if hasattr(trader, 'get_sol_balance') else 0
            
            tokens = trader.get_all_tokens() if hasattr(trader, 'get_all_tokens') else []
            for token in tokens:
                assets.append({
                    "asset": token.get('symbol', token.get('mint', 'Unknown')[:6]),
                    "amount": token.get('amount', 0),
                    "price": token.get('price', 0),
                    "value_usdt": token.get('value_usd', 0),
                    "type": "MEME"
                })
        except Exception as e:
            logger.error(f"Error fetching wallet tokens: {e}")
    
    result = {
        "usdt_balance": total_sol * 142,  # Approximate SOL->USD
        "sol_balance": total_sol,
        "assets": sorted(assets, key=lambda x: x['value_usdt'], reverse=True)
    }
    
    api_cache.set(f"port_{user_id}", result)
    return result

@app.get("/positions/{user_id}")
async def get_positions(user_id: int):
    """Get DEX meme positions (not Kraken positions)."""
    cached = api_cache.get(f"pos_{user_id}")
    if cached: return cached
    
    positions = []
    alert_sys = get_alert_system()
    
    if alert_sys and hasattr(alert_sys, 'dex_traders'):
        for trader in alert_sys.dex_traders:
            trader_user_id = getattr(trader, 'user_id', 1)
            if trader_user_id == user_id or user_id == 1:
                # Get positions from trader
                for mint, pos_data in getattr(trader, 'positions', {}).items():
                    entry_price = pos_data.get('entry_price', 0)
                    current_price = pos_data.get('current_price', entry_price)
                    profit_pct = ((current_price - entry_price) / entry_price * 100) if entry_price > 0 else 0
                    
                    positions.append({
                        "symbol": pos_data.get('symbol', mint[:8] + '...'),
                        "entry": entry_price,
                        "current": current_price,
                        "profit": f"{'+' if profit_pct >= 0 else ''}{profit_pct:.2f}%",
                        "side": "HOLD",
                        "type": "MEME"
                    })
                break
    
    api_cache.set(f"pos_{user_id}", positions)
    return positions

@app.get("/trades/{user_id}")
async def get_trades(user_id: int, db: Session = Depends(get_db)):
    """Get DEX trade history (excluding old Kraken trades)."""
    import models
    from datetime import datetime
    
    # DEX-only mode started 2026-01-13 - filter out older Kraken trades
    dex_start_date = datetime(2026, 1, 13)
    
    trades = db.query(models.Trade).filter(
        models.Trade.user_id == user_id,
        models.Trade.timestamp >= dex_start_date,
        # Exclude Kraken format symbols (contain /USDT)
        ~models.Trade.symbol.contains('/USDT')
    ).order_by(models.Trade.timestamp.desc()).limit(20).all()
    
    formatted = []
    for t in trades:
        formatted.append({
            "type": t.side,
            "symbol": t.symbol,
            "price": round(t.price, 8) if t.price else 0,
            "amount": t.amount,
            "time": t.timestamp.strftime("%Y-%m-%d %H:%M:%S") if t.timestamp else ""
        })
    
    return formatted

@app.get("/stats/{user_id}")
async def get_stats(user_id: int, db: Session = Depends(get_db)):
    """Get trading stats focused on DEX (excluding old Kraken trades)."""
    import models
    from datetime import datetime
    
    # DEX-only mode - start fresh from 2026-01-13
    dex_start_date = datetime(2026, 1, 13)
    
    trades = db.query(models.Trade).filter(
        models.Trade.user_id == user_id,
        models.Trade.timestamp >= dex_start_date,
        ~models.Trade.symbol.contains('/USDT')
    ).all()
    
    total_profit = 0
    if trades:
        sells = sum([float(t.cost or 0) for t in trades if t.side == 'SELL'])
        buys = sum([float(t.cost or 0) for t in trades if t.side == 'BUY'])
        total_profit = sells - buys
    
    alert_sys = get_alert_system()
    is_running = alert_sys is not None and getattr(alert_sys, 'ready', False)
    whale_count = 0
    if alert_sys and hasattr(alert_sys, 'copy_trader'):
        whale_count = len(getattr(alert_sys.copy_trader, 'qualified_wallets', [])) // 2
    
    return {
        "total_profit": f"${round(total_profit, 2)}",
        "active_bots_count": 1 if is_running else 0,
        "active_bot_names": f"🐋 Whale Hunter ({whale_count} tracked)" if is_running else "Connecting...",
        "whales_tracked": whale_count
    }

@app.get("/whale_activity")
async def get_whale_activity():
    """Get current whale swarm activity."""
    alert_sys = get_alert_system()
    
    if not alert_sys or not hasattr(alert_sys, 'copy_trader'):
        return {"signals": [], "whale_count": 0}
    
    copy_trader = alert_sys.copy_trader
    
    # Get swarm signals
    signals = []
    if hasattr(copy_trader, 'activity_cache'):
        for mint, activities in copy_trader.activity_cache.items():
            if len(activities) >= 2:  # At least 2 whales
                signals.append({
                    "mint": mint,
                    "whale_count": len(activities),
                    "is_swarm": len(activities) >= 3
                })
    
    return {
        "signals": sorted(signals, key=lambda x: x['whale_count'], reverse=True)[:10],
        "whale_count": len(getattr(copy_trader, 'qualified_wallets', [])) // 2
    }

# ============================================
# HELIUS WEBHOOK (Keep original)
# ============================================

@app.post("/helius/webhook")
async def helius_webhook(request: Request, background_tasks: BackgroundTasks):
    """
    Receives pushed transactions from Helius.
    Payload is a list of 'Enhanced Transaction' objects.
    """
    try:
        payload = await request.json()
        if not isinstance(payload, list):
            payload = [payload]
        
        background_tasks.add_task(process_helius_data, payload)
        return {"status": "received"}
    except Exception as e:
        logger.error(f"❌ Webhook Error: {e}")
        return {"status": "error", "message": str(e)}

async def process_helius_data(transactions):
    """Bridge the data to the AlertSystem/CopyTrader."""
    if bot_instance is None:
        logger.warning("⚠️ Bot instance not linked. Data dropped.")
        return

    try:
        import asyncio
        alert_system = None
        for _ in range(60):
            alert_system = bot_instance.get_cog("AlertSystem")
            if alert_system and getattr(alert_system, 'ready', False):
                break
            await asyncio.sleep(0.5)
            
        if not alert_system:
            logger.warning("⚠️ AlertSystem Cog not found after 30s wait. Data dropped.")
            return
            
        if not getattr(alert_system, 'ready', False):
            logger.warning("⚠️ AlertSystem found but NOT READY after 30s. Data dropped.")
            return

        # 1. Update activity cache in CopyTrader (for BUYs)
        added = alert_system.copy_trader.process_transactions(transactions)
        
        # 1b. Track whale activity
        for tx in transactions:
            wallet = tx.get('feePayer')
            if wallet and wallet in alert_system.copy_trader.qualified_wallets:
                alert_system.copy_trader.update_whale_activity(wallet)
        
        # 2. INSTANT EXIT DETECTION
        held_tokens = set()
        for trader in alert_system.dex_traders:
            held_tokens.update(trader.positions.keys())
            
        if held_tokens:
            sell_signals = alert_system.copy_trader.detect_whale_sells(transactions, held_tokens)
            for mint in sell_signals:
                logger.warning(f"🚨 INSTANT EXIT TRIGGERED FOR: {mint[:16]}...")
                await alert_system.trigger_instant_exit(mint)
        
    except Exception as e:
        logger.error(f"❌ Error processing webhook data: {e}")

def set_bot_instance(bot):
    global bot_instance
    bot_instance = bot
    logger.info("🤖 Bot instance linked to Webhook Listener.")
