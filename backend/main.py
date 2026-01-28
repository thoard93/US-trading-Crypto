"""
DEGEN DEX - Meme Token Creation Platform
Focused entry point for auto-launching meme tokens on Solana/Pump.fun.
"""
import asyncio
import os
import logging
from dotenv import load_dotenv

load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

async def main():
    """Main entry point for the token creation bot."""
    
    logger.info("🚀 DEGEN DEX - Meme Token Creation Platform Starting...")
    
    # Initialize database
    from database import init_db
    init_db()
    logger.info("✅ Database initialized")
    
    # Initialize DexTrader (core trading/token creation)
    from dex_trader import DexTrader
    trader = DexTrader()
    logger.info(f"✅ DexTrader initialized. Wallet: {trader.wallet_address[:8] if trader.wallet_address else 'None'}...")
    
    # Initialize TrendHunter (Twitter + PumpPortal discovery)
    from trend_hunter import TrendHunter
    hunter = TrendHunter()
    logger.info("✅ TrendHunter initialized")
    
    # Initialize MoversTracker (Phase 69: Historical mover data collection)
    from movers_tracker import get_movers_tracker, start_movers_tracking
    movers_tracker = get_movers_tracker()
    asyncio.create_task(start_movers_tracking())
    logger.info("✅ MoversTracker initialized (background collection active)")
    
    # Initialize AutoLauncher
    from auto_launcher import AutoLauncher
    launcher = AutoLauncher(trader, hunter)
    logger.info("✅ AutoLauncher initialized")
    
    # Initialize Discord Bot
    from bot import DegenBot
    bot = DegenBot(trader, launcher, hunter)
    
    # Start the Discord bot (this runs the event loop)
    discord_token = os.getenv('DISCORD_BOT_TOKEN')
    if discord_token:
        logger.info("🤖 Starting Discord Bot...")
        await bot.start(discord_token)
    else:
        logger.warning("⚠️ No DISCORD_BOT_TOKEN found. Running in headless mode...")
        # Run auto-launcher cycle in headless mode
        while True:
            try:
                await launcher.run_cycle()
                await asyncio.sleep(300)  # 5 minute cycles
            except Exception as e:
                logger.error(f"❌ Cycle error: {e}")
                await asyncio.sleep(60)

if __name__ == "__main__":
    asyncio.run(main())
