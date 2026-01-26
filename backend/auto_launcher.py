"""
Auto Launcher - Orchestrates automatic token launches based on trending keywords.
Includes safety controls and Discord integration.
"""
import os
import logging
import asyncio
from datetime import datetime, timedelta

class AutoLauncher:
    """
    Manages the automatic token launch pipeline.
    Includes safety limits, queue management, and Discord notifications.
    """
    def __init__(self, dex_trader=None, meme_creator=None, trend_hunter=None):
        self.logger = logging.getLogger(__name__)
        self.dex_trader = dex_trader
        self.meme_creator = meme_creator
        self.trend_hunter = trend_hunter
        
        # Configuration (can be overridden via Discord commands)
        self.enabled = os.getenv('AUTO_LAUNCH_ENABLED', 'true').lower() == 'true'  # 🚀 Auto-enabled on startup
        self.max_daily_launches = int(os.getenv('AUTO_LAUNCH_MAX_DAILY', '5'))
        self.min_sol_balance = float(os.getenv('AUTO_LAUNCH_MIN_SOL', '0.1'))
        self.volume_seed_sol = float(os.getenv('AUTO_LAUNCH_VOLUME_SEED', '0.5'))  # 0.5 SOL for ~5% bonding curve
        
        # State tracking
        self.launched_today = []  # List of {keyword, mint, timestamp}
        self.launch_queue = []    # Keywords waiting to be launched
        self._last_reset = datetime.utcnow().date()
        
        # Cooldown tracking (keyword -> last launch timestamp)
        self._keyword_cooldowns = {}
        self.cooldown_hours = 24
        self.boosted_volume = None  # Temporary boost for the next launch
        
        # Volume simulation settings
        self.volume_sim_enabled = os.getenv('AUTO_LAUNCH_VOLUME_SIM', 'false').lower() == 'true'
        self.volume_sim_rounds = int(os.getenv('AUTO_LAUNCH_VOLUME_ROUNDS', '10'))
        self.volume_sim_amount = float(os.getenv('AUTO_LAUNCH_VOLUME_AMOUNT', '0.01'))
        self.volume_sim_delay = int(os.getenv('AUTO_LAUNCH_VOLUME_DELAY', '30'))
    
    def set_boost(self, amount):
        """Set a temporary boost for the next launch."""
        self.boosted_volume = amount
        return self.boosted_volume

    def is_enabled(self):
        """Check if auto-launch is enabled."""
        return self.enabled
    
    def toggle(self, enabled=None):
        """Toggle auto-launch on/off."""
        if enabled is None:
            self.enabled = not self.enabled
        else:
            self.enabled = enabled
        return self.enabled
    
    def get_status(self):
        """Get current auto-launch status for Discord display."""
        return {
            "enabled": self.enabled,
            "launches_today": len(self.launched_today),
            "max_daily": self.max_daily_launches,
            "queue_size": len(self.launch_queue),
            "min_sol": self.min_sol_balance,
            "volume_seed": self.volume_seed_sol,
            "boost": self.boosted_volume
        }
    
    def configure(self, **kwargs):
        """Update configuration settings."""
        if 'max_daily' in kwargs:
            self.max_daily_launches = int(kwargs['max_daily'])
        if 'min_sol' in kwargs:
            self.min_sol_balance = float(kwargs['min_sol'])
        if 'volume_seed' in kwargs:
            self.volume_seed_sol = float(kwargs['volume_seed'])
        return self.get_status()
    
    def _reset_daily_counter(self):
        """Reset daily launch counter at midnight."""
        today = datetime.utcnow().date()
        if today > self._last_reset:
            self.launched_today = []
            self._last_reset = today
            self.logger.info("🔄 Daily launch counter reset")
    
    def _check_cooldown(self, keyword):
        """Check if keyword is on cooldown."""
        keyword_upper = keyword.upper()
        if keyword_upper in self._keyword_cooldowns:
            cooldown_until = self._keyword_cooldowns[keyword_upper]
            if datetime.utcnow() < cooldown_until:
                return False
        return True
    
    def _set_cooldown(self, keyword):
        """Set cooldown for a keyword."""
        keyword_upper = keyword.upper()
        self._keyword_cooldowns[keyword_upper] = datetime.utcnow() + timedelta(hours=self.cooldown_hours)
    
    def clear_cooldown(self, keyword):
        """Clear cooldown for a specific keyword (useful after failed launches)."""
        keyword_upper = keyword.upper()
        if keyword_upper in self._keyword_cooldowns:
            del self._keyword_cooldowns[keyword_upper]
            return True
        return False
    
    def check_safety_limits(self):
        """
        Check all safety limits before launching.
        Returns (can_launch: bool, reason: str)
        """
        self._reset_daily_counter()
        
        # Check daily limit
        if len(self.launched_today) >= self.max_daily_launches:
            return False, f"Daily limit reached ({self.max_daily_launches})"
        
        # Check SOL balance
        if self.dex_trader:
            balance = self.dex_trader.get_sol_balance()
            if balance < self.min_sol_balance:
                return False, f"Low SOL balance ({balance:.4f} < {self.min_sol_balance})"
        
        return True, "OK"
    
    def is_keyword_launched(self, keyword):
        """Check if keyword has been launched recently (in DB or cooldown)."""
        # Check cooldown
        if not self._check_cooldown(keyword):
            return True
        
        # Check DB for previous launches
        try:
            from database import SessionLocal
            from models import LaunchedKeyword
            
            db = SessionLocal()
            cutoff = datetime.utcnow() - timedelta(hours=self.cooldown_hours)
            
            exists = db.query(LaunchedKeyword).filter(
                LaunchedKeyword.keyword == keyword.upper(),
                LaunchedKeyword.launched_at > cutoff
            ).first()
            
            db.close()
            return exists is not None
            
        except Exception as e:
            self.logger.error(f"DB check error: {e}")
            return False  # Allow launch if DB check fails
    
    def _save_launch(self, keyword, mint_address, name=None, symbol=None):
        """Save launch to database."""
        try:
            from database import SessionLocal
            from models import LaunchedKeyword
            
            db = SessionLocal()
            new_launch = LaunchedKeyword(
                keyword=keyword.upper(),
                name=name,
                symbol=symbol,
                mint_address=mint_address,
                launched_at=datetime.utcnow()
            )
            db.add(new_launch)
            db.commit()
            db.close()
            
            self.logger.info(f"💾 Saved launch to DB: {keyword} -> {mint_address}")
            
        except Exception as e:
            self.logger.error(f"Error saving launch: {e}")
    
    async def discover_and_queue(self):
        """
        Discover trending keywords and add to launch queue.
        Called periodically by the background loop.
        """
        if not self.enabled:
            return 0
        
        if not self.trend_hunter:
            self.logger.warning("TrendHunter not initialized")
            return 0
        
        try:
            # 🛡️ CRITICAL: Run in thread to prevent Discord heartbeat timeout
            keywords = await asyncio.to_thread(self.trend_hunter.get_trending_keywords, 5)
            added = 0
            
            for keyword in keywords:
                # Skip if already launched or queued
                if self.is_keyword_launched(keyword):
                    continue
                if keyword.upper() in [k.upper() for k in self.launch_queue]:
                    continue
                
                # Use AI filter if available (also run in thread)
                is_worthy = await asyncio.to_thread(self.trend_hunter.is_meme_worthy, keyword)
                if is_worthy:
                    self.launch_queue.append(keyword)
                    added += 1
                    self.logger.info(f"📥 Queued for launch: {keyword}")
            
            return added
            
        except Exception as e:
            self.logger.error(f"Error discovering trends: {e}")
            return 0
    
    async def process_queue(self, bot=None, channel_id=None):
        """
        Process one item from the launch queue.
        Returns launch result or None if nothing to process.
        """
        if not self.enabled:
            return None
        
        if not self.launch_queue:
            return None
        
        # Safety check
        can_launch, reason = self.check_safety_limits()
        if not can_launch:
            self.logger.warning(f"⚠️ Cannot launch: {reason}")
            return {"error": reason}
        
        # Get next keyword from queue
        keyword = self.launch_queue.pop(0)
        
        # Double-check it hasn't been launched while queued
        if self.is_keyword_launched(keyword):
            self.logger.info(f"⏭️ Skipping {keyword} (already launched)")
            return None
        
        # Perform the launch
        result = await self.launch_one(keyword, bot, channel_id)
        return result
    
    async def launch_one(self, keyword, bot=None, channel_id=None):
        """
        Execute a full launch for a single keyword.
        """
        self.logger.info(f"🚀 AUTO-LAUNCHING: {keyword}")
        
        try:
            # Step 1: Generate meme pack (run in thread to avoid blocking heartbeat)
            if not self.meme_creator:
                return {"error": "MemeCreator not initialized"}
            
            # 🛡️ CRITICAL: Run in thread to prevent Discord heartbeat timeout
            pack = await asyncio.to_thread(self.meme_creator.create_full_meme, keyword)
            if not pack:
                return {"error": f"Failed to generate meme for {keyword}"}
            
            # Step 2: Launch on Pump.fun
            if not self.dex_trader:
                return {"error": "DexTrader not initialized"}
            
            # PHASE 47: Apply Boost if active
            buy_amount = self.boosted_volume if self.boosted_volume is not None else self.volume_seed_sol
            self.logger.info(f"🔥 Launching with seed: {buy_amount} SOL {'(BOOSTED)' if self.boosted_volume else ''}")
            
            result = self.dex_trader.create_pump_token(
                name=pack['name'],
                symbol=pack['ticker'],
                description=pack['description'],
                image_url=pack['image_url'],
                sol_buy_amount=buy_amount,
                use_jito=False  # DISABLED: Jito bundles drop silently. Using standard RPC for now.
            )
            
            # Reset boost after launch attempt
            self.boosted_volume = None
            
            if result.get('error'):
                return result
            
            # Step 3: Record the launch
            mint_address = result.get('mint', 'unknown')
            self.launched_today.append({
                "keyword": keyword,
                "mint": mint_address,
                "timestamp": datetime.utcnow()
            })
            self._set_cooldown(keyword)
            self._save_launch(keyword, mint_address, name=pack['name'], symbol=pack['ticker'])
            
            # Step 4: Notify Discord
            if bot and channel_id:
                try:
                    import discord
                    channel = bot.get_channel(int(channel_id))
                    if channel:
                        embed = discord.Embed(
                            title="🤖 AUTO-LAUNCH SUCCESS!",
                            description=f"Successfully deployed **{pack['name']}** on-chain.",
                            color=discord.Color.green()
                        )
                        embed.add_field(name="Keyword", value=keyword, inline=True)
                        embed.add_field(name="Ticker", value=f"${pack['ticker']}", inline=True)
                        embed.add_field(name="Mint", value=f"`{mint_address}`", inline=False)
                        embed.add_field(name="Pump.fun", value=f"[View on Pump.fun](https://pump.fun/{mint_address})", inline=False)
                        
                        if pack.get('image_url'):
                            embed.set_image(url=pack['image_url'])
                            
                        await channel.send(embed=embed)
                        
                        # Step 5: Volume Simulation (if enabled)
                        if self.volume_sim_enabled and self.dex_trader:
                            await channel.send(f"📊 **Volume Simulation** starting in 30s on `{pack['name']}`...")
                            await asyncio.sleep(30)  # Wait before starting simulation
                            
                            sim_result = await self.dex_trader.simulate_volume(
                                mint_address,
                                rounds=self.volume_sim_rounds,
                                sol_per_round=self.volume_sim_amount,
                                delay_seconds=self.volume_sim_delay
                            )
                            
                            if sim_result.get('success'):
                                await channel.send(f"✅ Volume simulation complete! {sim_result['buys']} buys, {sim_result['sells']} sells")
                            else:
                                await channel.send(f"⚠️ Volume simulation had issues. Check logs.")
                                
                except Exception as e:
                    self.logger.error(f"Discord notification error: {e}")
            
            return {
                "success": True,
                "keyword": keyword,
                "name": pack['name'],
                "ticker": pack['ticker'],
                "mint": mint_address
            }
            
        except Exception as e:
            self.logger.error(f"Launch error: {e}")
            import traceback
            traceback.print_exc()
            return {"error": str(e)}


# Test script
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    launcher = AutoLauncher()
    
    print("📊 Auto-Launcher Status:")
    status = launcher.get_status()
    for key, value in status.items():
        print(f"  {key}: {value}")
