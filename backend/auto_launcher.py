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
        
        # State tracking - Phase 66: Per-Wallet Daily Limits
        self.launched_today = {}  # Dict of wallet_key -> [launches]
        self.launch_queue = []    # Keywords waiting to be launched
        self._last_reset = datetime.utcnow().date()
        self._next_creator_key = None  # Track which wallet will create next token
        
        # Cooldown tracking (keyword -> last launch timestamp)
        self._keyword_cooldowns = {}
        self.cooldown_hours = 24
        self.boosted_volume = None  # Temporary boost for the next launch
        
        # Volume simulation settings - ENABLED BY DEFAULT FOR AUTOPILOT
        self.volume_sim_enabled = os.getenv('AUTO_LAUNCH_VOLUME_SIM', 'true').lower() == 'true'
        self.volume_sim_rounds = int(os.getenv('AUTO_LAUNCH_VOLUME_ROUNDS', '5'))  # Phase 66: Lowered to 5 for cost savings
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
        
        # Phase 66: Per-Wallet-Type Creation Limits
        # Primary main (SOLANA_PRIVATE_KEY): Uses max_daily_launches (10)
        # Secondary mains (SOLANA_MAIN_KEYS): Lower limit to share costs
        # Support wallets: Minimal creation for organic appearance
        self.secondary_main_limit = int(os.getenv('SECONDARY_MAIN_LIMIT', '5'))  # Dylan's wallet limit
        self.support_wallet_creation_limit = int(os.getenv('SUPPORT_WALLET_LIMIT', '2'))
    
    def _get_next_creation_wallet(self):
        """
        Smart wallet selection for token creation with differentiated limits:
        - Primary main (first SOLANA_PRIVATE_KEY): max_daily_launches (10)
        - Secondary mains (SOLANA_MAIN_KEYS): secondary_main_limit (5)
        - Support wallets: support_wallet_creation_limit (2)
        """
        if not self.dex_trader or not hasattr(self.dex_trader, 'wallet_manager'):
            return None
        
        wm = self.dex_trader.wallet_manager
        primary_key = wm.primary_key  # Your main wallet
        secondary_keys = wm.get_secondary_main_keys() or []  # Dylan's wallet(s)
        support_keys = wm.get_all_support_keys() or []
        
        # Build candidate list with per-wallet-type limits
        candidates = []
        
        # Primary main: max_daily_launches (10)
        if primary_key:
            count = self._wallet_creation_counts.get(primary_key, 0)
            if count < self.max_daily_launches:
                candidates.append(primary_key)
        
        # Secondary mains: secondary_main_limit (5)
        for sk in secondary_keys:
            count = self._wallet_creation_counts.get(sk, 0)
            if count < self.secondary_main_limit:
                candidates.append(sk)
        
        # Support wallets: support_wallet_creation_limit (2)
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
        total_launches = sum(len(v) for v in self.launched_today.values())
        wallet_count = len(self.launched_today) if self.launched_today else 0
        return {
            "enabled": self.enabled,
            "launches_today": total_launches,
            "wallets_active": wallet_count,
            "max_daily_per_wallet": self.max_daily_launches,
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
        """Reset daily launch counters at midnight.
        Note: Support wallet creation counts are LIFETIME, not daily - they never reset.
        """
        today = datetime.utcnow().date()
        if today > self._last_reset:
            self.launched_today = {}  # Reset daily launch tracking
            
            # Only reset MAIN wallet creation counts, keep support wallet counts
            # Support wallets have a LIFETIME limit (e.g., 2 total ever)
            if hasattr(self, 'dex_trader') and hasattr(self.dex_trader, 'wallet_manager'):
                wm = self.dex_trader.wallet_manager
                support_keys = set(wm.get_all_support_keys() or [])
                # Preserve support wallet counts, reset main wallet counts
                preserved = {k: v for k, v in self._wallet_creation_counts.items() if k in support_keys}
                self._wallet_creation_counts = preserved
            else:
                # No wallet manager yet, just reset (will be populated on first use)
                self._wallet_creation_counts = {}
            
            self._last_reset = today
            self.logger.info("🔄 Daily launch counters reset (main wallets only, support limits preserved)")
    
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
        Phase 66: Now checks PER-WALLET daily limits, not global.
        """
        self._reset_daily_counter()
        
        # Pre-select which wallet will create the next token
        self._next_creator_key = self._get_next_creation_wallet()
        
        if not self._next_creator_key:
            return False, "No wallets available (all at daily/creation limit)"
        
        # Check per-wallet daily limit
        wallet_launches = len(self.launched_today.get(self._next_creator_key, []))
        if wallet_launches >= self.max_daily_launches:
            # Try to find another wallet with remaining capacity
            wm = self.dex_trader.wallet_manager if hasattr(self.dex_trader, 'wallet_manager') else None
            if wm:
                all_keys = wm.get_all_keys() or []
                for key in all_keys:
                    if len(self.launched_today.get(key, [])) < self.max_daily_launches:
                        self._next_creator_key = key
                        break
                else:
                    total = sum(len(v) for v in self.launched_today.values())
                    return False, f"All wallets at daily limit ({total} total launches)"
        
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
            
            # Phase 66: Use wallet pre-selected by check_safety_limits
            creator_key = self._next_creator_key or self._get_next_creation_wallet()
            creator_label = "Main"
            if creator_key and hasattr(self.dex_trader, 'wallet_manager'):
                creator_label = self.dex_trader.wallet_manager.get_wallet_label(creator_key)
            print(f"🎨 Token being created by: {creator_label}")
            
            # Determine buy amount (apply boost if set)
            buy_amount = self.boosted_volume if self.boosted_volume else self.volume_seed_sol
            self.logger.info(f"💰 AUTO-LAUNCH: Creating token {pack['name']} by {creator_label} with {buy_amount} SOL...")
            
            # 🛡️ CRITICAL: Run in thread to prevent Discord heartbeat timeout
            # create_pump_token is synchronous and can block on network calls
            result = await asyncio.to_thread(
                self.dex_trader.create_pump_token,
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
            
            # Step 3: Record the launch (per-wallet)
            mint_address = result.get('mint', 'unknown')
            if creator_key not in self.launched_today:
                self.launched_today[creator_key] = []
            self.launched_today[creator_key].append({
                "keyword": keyword,
                "mint": mint_address,
                "timestamp": datetime.utcnow()
            })
            wallet_count = len(self.launched_today[creator_key])
            total_count = sum(len(v) for v in self.launched_today.values())
            self.logger.info(f"📊 Launch recorded: {creator_label} now at {wallet_count}/{self.max_daily_launches} (total: {total_count})")
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
                        
                        # Phase 70: SWARM STRATEGY - Hold and Dump
                        # All support wallets buy visible amounts, then wait for exit trigger
                        
                        if hasattr(self.dex_trader, 'wallet_manager'):
                            support_keys = self.dex_trader.wallet_manager.get_all_support_keys()
                            
                            if support_keys:
                                # Get swarm config from env
                                swarm_buy = float(os.getenv('SWARM_BUY_AMOUNT', '0.05'))
                                
                                await channel.send(f"🐝 **SWARM BUY**: {len(support_keys)} wallets × {swarm_buy} SOL...")
                                
                                # All support wallets buy at launch (visible above 0.05 filter)
                                buy_tasks = []
                                for i, key in enumerate(support_keys):
                                    label = f"S{i+1}"
                                    print(f"🐝 [{pack['ticker']}] {label} buying {swarm_buy} SOL...")
                                    
                                    task = asyncio.create_task(asyncio.to_thread(
                                        self.dex_trader.pump_buy, 
                                        mint_address, 
                                        sol_amount=swarm_buy,
                                        payer_key=key
                                    ))
                                    buy_tasks.append((label, task))
                                
                                # Wait for all buys to complete
                                buy_results = []
                                for label, task in buy_tasks:
                                    try:
                                        result = await task
                                        if result and not result.get('error'):
                                            buy_results.append(('success', label))
                                            print(f"✅ {label} buy success")
                                        else:
                                            buy_results.append(('failed', label))
                                            print(f"⚠️ {label} buy failed: {result}")
                                    except Exception as e:
                                        buy_results.append(('error', label))
                                        print(f"❌ {label} buy error: {e}")
                                
                                success_count = sum(1 for r in buy_results if r[0] == 'success')
                                await channel.send(f"🐝 **SWARM READY**: {success_count}/{len(support_keys)} wallets positioned!")
                                
                                # Start exit coordinator to monitor for dump
                                if success_count > 0:
                                    from exit_coordinator import get_exit_coordinator
                                    
                                    exit_coord = get_exit_coordinator(self.dex_trader)
                                    target_mc = float(os.getenv('SWARM_EXIT_MC', '25000'))
                                    timeout = int(os.getenv('SWARM_EXIT_TIMEOUT', '600'))
                                    
                                    await channel.send(f"🎯 **EXIT MONITOR**: Watching for ${target_mc:,.0f} MC or {timeout//60}min timeout...")
                                    
                                    # Filter to only wallets that successfully bought
                                    bought_keys = [support_keys[i] for i, (status, _) in enumerate(buy_results) if status == 'success']
                                    
                                    # Create exit callback for Discord updates
                                    async def exit_callback(msg):
                                        try:
                                            await channel.send(f"🚨 [{pack['ticker']}] {msg}")
                                        except:
                                            pass
                                    
                                    # Start monitoring in background
                                    asyncio.create_task(
                                        exit_coord.start_exit_monitor(
                                            mint_address,
                                            bought_keys,
                                            callback=exit_callback
                                        )
                                    )
                            else:
                                await channel.send("⚠️ No support wallets configured - skipping swarm")
                                
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
