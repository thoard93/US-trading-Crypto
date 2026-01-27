"""
Auto Launcher - Orchestrates automatic token launches based on trending keywords.
Includes safety controls and Discord integration.
"""
import os
import re
import random
import logging
import asyncio
from datetime import datetime, timedelta
from engagement_framer import EngagementFramer

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
        self.engagement_framer = EngagementFramer(dex_trader)
        
        # Configuration (can be overridden via Discord commands)
        self.enabled = os.getenv('AUTO_LAUNCH_ENABLED', 'true').lower() == 'true'  # 🚀 Auto-enabled on startup
        self.max_daily_launches = int(os.getenv('AUTO_LAUNCH_MAX_DAILY', '10'))  # MEGA BOT: 10 launches/day
        self.min_sol_balance = float(os.getenv('AUTO_LAUNCH_MIN_SOL', '0.02'))  # Lowered for lean operation
        self.volume_seed_sol = float(os.getenv('AUTO_LAUNCH_VOLUME_SEED', '0.01'))  # MOON BIAS: Default to 0.01 SOL
        
        # State tracking
        self.launched_today = []  # List of {keyword, mint, timestamp}
        self.launch_queue = []    # Keywords waiting to be launched
        self._last_reset = datetime.utcnow().date()
        
        # Cooldown tracking (keyword -> last launch timestamp)
        self._keyword_cooldowns = {}
        self.cooldown_hours = 24
        self.boosted_volume = None  # Temporary boost for the next launch
        
        # Volume simulation settings - ENABLED BY DEFAULT FOR AUTOPILOT
        self.volume_sim_enabled = os.getenv('AUTO_LAUNCH_VOLUME_SIM', 'true').lower() == 'true'
        self.volume_sim_rounds = int(os.getenv('AUTO_LAUNCH_VOLUME_ROUNDS', '10'))
        self.volume_sim_amount = float(os.getenv('AUTO_LAUNCH_VOLUME_AMOUNT', '0.01'))
        self.volume_sim_delay = int(os.getenv('AUTO_LAUNCH_VOLUME_DELAY', '30'))
        
        # Source filter for autopilot (pump, twitter, dex, or None for all)
        # FIXED: Accept all sources since Pump.fun API is unreliable (Cloudflare blocks)
        self.source_filter = None  # Accept all sources: pump, twitter, dex
        
        # Phase 55: Social Consistency
        self.fixed_twitter = os.getenv('AUTO_LAUNCH_X_HANDLE', '')
        self.fixed_telegram = os.getenv('AUTO_LAUNCH_TG_LINK', '')
        
        # Phase 56: Parallel Token Support (now tracks per-wallet sims)
        self.active_simulations = {}  # "mint:wallet_idx" -> Task object
        self.max_parallel_sims = 10   # Increased: 2 wallets × 5 tokens = 10 max concurrent
        
        # Phase 59: Multi-Wallet Token Creation (Organic Bot Farm)
        # Rotate token creation across wallets for authentic trading history
        self._creation_wallet_index = 0
        self._wallet_creation_counts = {}  # key -> creation count
        self.support_wallet_creation_limit = 2  # Support wallets create max 2 tokens (for organic look)
    
    def _get_next_creation_wallet(self):
        """
        Smart wallet selection for token creation:
        - Main wallets: Unlimited creation
        - Support wallets: Limited to self.support_wallet_creation_limit tokens for organic appearance
        """
        if not self.dex_trader or not hasattr(self.dex_trader, 'wallet_manager'):
            return None
        
        wm = self.dex_trader.wallet_manager
        main_keys = wm.get_all_main_keys() or []
        support_keys = wm.get_all_support_keys() or []
        
        # Build candidate list: all main wallets + support wallets under limit
        candidates = list(main_keys)  # Main wallets are always candidates
        
        for sk in support_keys:
            count = self._wallet_creation_counts.get(sk, 0)
            if count < self.support_wallet_creation_limit:
                candidates.append(sk)
        
        if not candidates:
            return None
        
        # Round-robin through eligible candidates
        key = candidates[self._creation_wallet_index % len(candidates)]
        self._creation_wallet_index += 1
        
        # Track creation count
        self._wallet_creation_counts[key] = self._wallet_creation_counts.get(key, 0) + 1
        
        return key
    
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
        MEGA BOT: Filters for Pump.fun-only trends by default.
        """
        if not self.enabled:
            return 0
        
        if not self.trend_hunter:
            self.logger.warning("TrendHunter not initialized")
            return 0
        
        try:
            # 🛡️ CRITICAL: Run in thread to prevent Discord heartbeat timeout
            # Get keywords WITH SOURCE to filter by Pump.fun
            keywords_with_source = await asyncio.to_thread(self.trend_hunter.get_trending_keywords, 10, True)
            added = 0
            
            for item in keywords_with_source:
                keyword = item['keyword']
                source = item['source']
                
                # MEGA BOT: Filter by source if configured
                if self.source_filter and source != self.source_filter:
                    self.logger.debug(f"Skipping {keyword} (source: {source}, filter: {self.source_filter})")
                    continue
                
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
                else:
                    self.logger.info(f"🚫 AI rejected: {keyword}")
            
            # Log queue status
            if added == 0 and len(keywords_with_source) > 0:
                self.logger.info(f"📋 Queue empty - all {len(keywords_with_source)} keywords filtered/launched")
            
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
            
            # PHASE 48: Add Placeholder Social Links to attract sniper bots
            clean_name = re.sub(r'[^a-zA-Z0-9]', '', pack['name']).lower()
            # Determine social links (Fixed vs Generated)
            twitter_link = self.fixed_twitter if self.fixed_twitter else f"https://x.com/{clean_name}_sol"
            tg_link = self.fixed_telegram if self.fixed_telegram else f"https://t.me/{clean_name}_portal"
            
            # Phase 59: Select which wallet creates this token (round-robin all wallets)
            creator_key = self._get_next_creation_wallet()
            creator_label = "Main"
            if creator_key and hasattr(self.dex_trader, 'wallet_manager'):
                creator_label = self.dex_trader.wallet_manager.get_wallet_label(creator_key)
            print(f"🎨 Token being created by: {creator_label}")
            
            # Determine buy amount (apply boost if set)
            buy_amount = self.boosted_volume if self.boosted_volume else self.volume_seed_sol
            print(f"💰 AUTO-LAUNCH: Buying {buy_amount} SOL of {pack['name']}...")
            
            result = self.dex_trader.create_pump_token(
                name=pack['name'],
                symbol=pack['ticker'],
                description=pack['description'],
                image_url=pack['image_url'],
                sol_buy_amount=buy_amount,
                use_jito=False,  # DISABLED: Jito bundles drop silently. Using standard RPC for now.
                twitter=twitter_link,
                telegram=tg_link,
                website='',
                payer_key=creator_key  # Phase 59: Rotating wallet for organic history!
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
            
            # Phase 55: Engagement Farming (Social Proof)
            # Post unhinged comments in background to build immediate hype
            if self.engagement_framer:
                asyncio.create_task(self.engagement_framer.farm_engagement(mint_address, count=3))
            
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
                        
                        # Phase 56: Bundled Support Buys & Background Simulation
                        
                        # 1. Bundled Support Buys (Holder Diversification)
                        if hasattr(self.dex_trader, 'wallet_manager'):
                            support_keys = self.dex_trader.wallet_manager.get_all_support_keys()
                            if support_keys:
                                print(f"🛡️ BUNDLING: Triggering {min(len(support_keys), 2)} support buys...")
                                for i in range(min(len(support_keys), 2)):
                                    # Very small buys to create holder "bubbles"
                                    support_buy_amount = round(random.uniform(0.005, 0.008), 4)
                                    asyncio.create_task(asyncio.to_thread(
                                        self.dex_trader.pump_buy, 
                                        mint_address, 
                                        sol_amount=support_buy_amount,
                                        payer_key=support_keys[i]
                                    ))
                        
                        # 2. Parallel Volume Simulation
                        if self.volume_sim_enabled and self.dex_trader:
                            # Check concurrency guard
                            if len(self.active_simulations) >= self.max_parallel_sims:
                                await channel.send(f"⚠️ **Parallel Limit reached** ({self.max_parallel_sims}). Skipping volume sim for `{pack['name']}`.")
                                self.logger.warning(f"Skipping volume sim for {mint_address} - already {len(self.active_simulations)} active.")
                            else:
                                # Get ALL wallets for parallel volume simulation
                                # EXCEPT the creator wallet (they'd show as "dev")
                                all_keys = []
                                if hasattr(self.dex_trader, 'wallet_manager'):
                                    all_keys = self.dex_trader.wallet_manager.get_all_keys() or []
                                
                                # Filter out the creator wallet - they're the "dev" on this token
                                sim_wallets = [k for k in all_keys if k != creator_key]
                                
                                if not sim_wallets:
                                    await channel.send(f"⚠️ **No non-creator wallets available** - skipping volume sim")
                                else:
                                    await channel.send(f"📊 **Volume Simulation** starting with {len(sim_wallets)} wallets on `{pack['name']}`...")
                                    
                                    # Start volume sim on EACH non-creator wallet in parallel
                                    for wallet_idx, wallet_key in enumerate(sim_wallets):
                                        wallet_label = f"W{wallet_idx+1}"
                                        wallet_short = wallet_key[:8]
                                        print(f"📊 [{pack['ticker']}] VolSim {wallet_label} starting: {wallet_short}...")
                                        
                                        # Create callback with wallet label for clarity
                                        def make_callback(label):
                                            async def cb(msg):
                                                try:
                                                    await channel.send(f"📊 [{label}] {msg}")
                                                except:
                                                    pass
                                            return cb
                                        
                                        # Randomize moon_bias per wallet for organic look (88-96%)
                                        wallet_moon_bias = round(random.uniform(0.88, 0.96), 2)
                                        print(f"📊 [{pack['ticker']}] {wallet_label} moon_bias: {wallet_moon_bias*100:.0f}%")
                                        
                                        sim_task = asyncio.create_task(self.dex_trader.simulate_volume(
                                            mint_address,
                                            rounds=self.volume_sim_rounds,
                                            sol_per_round=self.volume_sim_amount,
                                            delay_seconds=self.volume_sim_delay,
                                            callback=make_callback(wallet_label),
                                            moon_bias=wallet_moon_bias,  # Randomized per wallet!
                                            ticker=f"{pack['ticker']}-{wallet_label}",
                                            payer_key=wallet_key
                                        ))
                                        
                                        # Track with unique key per wallet
                                        sim_key = f"{mint_address}:{wallet_idx}"
                                        self.active_simulations[sim_key] = sim_task
                                        
                                        # Cleanup when done
                                        def make_cleanup(key, label, ticker):
                                            def cleanup(t):
                                                if key in self.active_simulations:
                                                    del self.active_simulations[key]
                                                    print(f"🧹 VolSim {label} finished for {ticker}. Active: {len(self.active_simulations)}")
                                            return cleanup
                                        
                                        sim_task.add_done_callback(make_cleanup(sim_key, wallet_label, pack['ticker']))
                                
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
