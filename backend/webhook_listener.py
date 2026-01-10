import os
import logging
from fastapi import FastAPI, Request, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import List, Optional

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

app = FastAPI(title="Helius Webhook Listener")

# Global reference to the bot/cog - will be set during bot startup
bot_instance = None

@app.get("/")
async def health_check():
    return {"status": "alive", "bot_connected": bot_instance is not None}

@app.post("/helius/webhook")
async def helius_webhook(request: Request, background_tasks: BackgroundTasks):
    """
    Receives pushed transactions from Helius.
    Payload is a list of 'Enhanced Transaction' objects.
    """
    # 1. Verify Request (Optional: check a secret header)
    # auth_header = request.headers.get("Authorization")
    # if auth_header != os.getenv("HELIUS_WEBHOOK_SECRET"):
    #     raise HTTPException(status_code=401, detail="Unauthorized")

    try:
        payload = await request.json()
        if not isinstance(payload, list):
            # Helius sometimes sends a single object or a different format
            payload = [payload]
            
        # logger.info(f"📥 Received Helius Webhook: {len(payload)} transactions")
        
        # 2. Process in background to avoid blocking Helius (Must respond < 5s)
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
        # Wait up to 30 seconds for the Cog to be ready (prevents startup race condition)
        import asyncio
        alert_system = None
        for _ in range(60): # 60 * 0.5s = 30s
            alert_system = bot_instance.get_cog("AlertSystem")
            if alert_system:
                break
            await asyncio.sleep(0.5)
            
        if not alert_system:
            logger.warning("⚠️ AlertSystem Cog not found after 30s wait. Data dropped.")
            return

        # 1. Update activity cache in CopyTrader (for BUYs)
        added = alert_system.copy_trader.process_transactions(transactions)
        
        # 2. INSTANT EXIT DETECTION: Check if any whale is selling tokens we hold
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
