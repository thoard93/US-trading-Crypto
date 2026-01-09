import os
import logging
from fastapi import FastAPI, Request, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import List, Optional

# Setup Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("WebhookListener")

# SILENCE Uvicorn Access Logs (They spam every single transaction)
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

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
        # Get the AlertSystem cog
        alert_system = bot_instance.get_cog("AlertSystem")
        if not alert_system:
            logger.warning("⚠️ AlertSystem Cog not found.")
            return

        # 1. Update activity cache in CopyTrader
        added = alert_system.copy_trader.process_transactions(transactions)
        
        if added > 0:
            logger.info(f"✅ Webhook added {added} new whale activities to cache.")
            
            # 2. Trigger Swarm Analysis immediately
            signals = alert_system.copy_trader.analyze_swarms()
            
            if signals:
                logger.info(f"🚀 WEBHOOK TRIGGERED SWARM: {signals}")
                # 3. Inform AlertSystem to handle execution (Discord alerts + trades)
                for mint in signals:
                    # Check if already holding logic is usually inside execute_swarm_trade or similar
                    await alert_system.execute_swarm_trade(mint)
        
    except Exception as e:
        logger.error(f"❌ Error processing webhook data: {e}")

def set_bot_instance(bot):
    global bot_instance
    bot_instance = bot
    logger.info("🤖 Bot instance linked to Webhook Listener.")
