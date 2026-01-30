import asyncio
import os
import logging
import json
import time
import requests
from datetime import datetime
from typing import Dict, List, Optional

# Core imports
import sys
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from dex_trader import DexTrader
# from trend_hunter import TrendHunter  # DISABLED: Not needed for sniping, saves API $
from movers_tracker import get_movers_tracker
from pump_portal_client import get_pump_portal_client  # NEW: Real-time token detection
from risk_manager import get_risk_manager  # NEW: Dynamic position sizing
from sniper_exit_coordinator import get_sniper_exit_coordinator
from wallet_manager import WalletManager
from discord_alerter import get_discord_alerter  # NEW: Webhook-based alerts

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("MarketSniper")

class DiscordAlerter:
    """Smart notification handler with anti-spam and importance filtering."""
    def __init__(self, channel_id: str):
        self.channel_id = channel_id
        self.last_alerts = {} # mint -> timestamp
        self.flood_cooldown = 300 # 5 minutes for non-critical alerts
        
    async def notify(self, message: str, title: str = "🎯 SNIPER ALERT", color: int = 0x9b59b6, critical: bool = False):
        if not self.channel_id: return
        
        # Anti-Spam: Critical alerts always go through
        now = time.time()
        if not critical:
            last_sent = self.last_alerts.get(message, 0)
            if now - last_sent < self.flood_cooldown: return
                
        try:
            from bot import get_discord_client
            import discord
            client = get_discord_client()
            if client:
                channel = client.get_channel(int(self.channel_id))
                if channel:
                    embed = discord.Embed(title=title, description=message, color=color)
                    embed.set_timestamp()
                    await channel.send(embed=embed)
                    self.last_alerts[message] = now
        except Exception as e:
            logger.debug(f"Discord notify error: {e}")

class MarketSniper:
    """
    High-precision Market Sniper for automated Solana token trading.
    Focuses on safety vetting, fast execution, and profit-taking tiers.
    """
    def __init__(self, dry_run=True):
        self.dry_run = dry_run
        self.trader = DexTrader()
        # self.hunter = TrendHunter()  # DISABLED: Save Twitter API costs
        self.tracker = get_movers_tracker()
        self.pump_portal = get_pump_portal_client()  # NEW: Real-time WebSocket
        self.risk_mgr = get_risk_manager(self.trader)  # NEW: Dynamic sizing
        self.wallets = WalletManager()
        self.exit_coord = get_sniper_exit_coordinator(self.trader)
        
        # Strategy Config
        # GROK TUNED SETTINGS (Jan 29 2026 - Open Funnel for Action)
        self.min_mc = float(os.getenv('SNIPER_MIN_MC', '7000'))  # Raised: 4k→7k for better quality entries
        self.max_mc = float(os.getenv('SNIPER_MAX_MC', '100000'))  # Still 100k cap
        self.min_momentum = float(os.getenv('SNIPER_MIN_MOMENTUM', '50'))  # Keep at 50
        self.buy_amount = float(os.getenv('SNIPER_BUY_SOL', '0.1'))  # Fallback only (risk_mgr handles sizing)
        self.require_socials = os.getenv('SNIPER_REQUIRE_SOCIALS', 'false').lower() == 'true'
        self.check_liquidity = os.getenv('SNIPER_CHECK_LIQUIDITY', 'false').lower() == 'true'  # DISABLED per Grok
        self.holder_threshold = float(os.getenv('SNIPER_HOLDER_THRESHOLD', '0.60'))  # 60% - relaxed for t=0 tokens
        
        # Smart Alerter (New webhook-based)
        self.alerter = get_discord_alerter()
        
        # Internal State
        self.active_positions = {} # mint -> position_data
        self.seen_tokens = set()
        self.recheck_queue = {}  # mint -> (token_data, scheduled_time) for concentration rechecks
        self.running = False

    async def start(self):
        """Main loop for the sniper."""
        logger.info(f"🚀 Sniper starting... Mode: {'DRY RUN' if self.dry_run else 'LIVE'}")
        self.running = True
        
        # TrendHunter DISABLED - not needed for sniping, saves Twitter API $
        # self.hunter.get_trending_keywords(limit=1) 
        
        # Register callback for PumpPortal new token events
        self.pump_portal.register_callback(self._on_new_token)
        
        # Start PumpPortal WebSocket in background (non-blocking)
        asyncio.create_task(self._run_pump_portal())
        
        while self.running:
            try:
                # ORPHAN AUDIT DISABLED: Was causing noise from old tokens
                # await self._audit_held_positions()

                # POLLING DISABLED: PumpPortal WebSocket handles discovery now
                # Old approach fetched /top-runners which returned mature tokens
                # Now we just wait for WebSocket events
                
                # Process recheck queue for concentration-failed tokens
                await self._process_recheck_queue()
                
                await asyncio.sleep(5)
                
            except Exception as e:
                logger.error(f"❌ Sniper loop error: {e}")
                await asyncio.sleep(5)
    
    async def _process_recheck_queue(self):
        """Re-evaluate tokens with multi-interval rechecks (20/40/60s) and rising trend validation."""
        if not self.recheck_queue:
            return
            
        now = time.time()
        to_remove = []
        
        for mint, check_data in list(self.recheck_queue.items()):
            # Handle old tuple format for backwards compatibility
            if isinstance(check_data, tuple):
                token_data, scheduled_time = check_data
                if now >= scheduled_time:
                    to_remove.append(mint)
                    top_holders_share = await self._get_holder_concentration(mint)
                    symbol = token_data.get('symbol', 'Unknown')
                    if top_holders_share <= self.holder_threshold:
                        logger.info(f"✅ [RECHECK PASSED] {symbol} - Concentration dropped to {top_holders_share*100:.1f}%")
                        self.seen_tokens.discard(mint)
                        if await self._should_snipe(token_data):
                            await self._execute_snipe(token_data)
                    else:
                        logger.info(f"❌ [RECHECK FAILED] {symbol} - Still {top_holders_share*100:.1f}% concentration")
                continue
            
            # New multi-interval format
            token_data = check_data.get('token_data', {})
            check_times = check_data.get('check_times', [])
            current_check = check_data.get('current_check', 0)
            prev_mc = check_data.get('prev_mc', 0)
            symbol = token_data.get('symbol', 'Unknown')
            
            if current_check >= len(check_times):
                to_remove.append(mint)
                continue
                
            if now >= check_times[current_check]:
                # Fetch current MC to check trend
                current_mc = await self.exit_coord._get_mc(mint) or 0
                
                if prev_mc > 0 and current_mc < prev_mc * 0.95:  # Dropped >5% during recheck
                    logger.warning(f"🚫 [RECHECK ABORT] {symbol} - MC dropped {((current_mc/prev_mc)-1)*100:.0f}% during wait")
                    to_remove.append(mint)
                    continue
                
                # Check concentration
                top_holders_share = await self._get_holder_concentration(mint)
                
                if top_holders_share <= self.holder_threshold:
                    logger.info(f"✅ [RECHECK {current_check+1}/3 PASSED] {symbol} - Concentration: {top_holders_share*100:.1f}%, MC rising")
                    self.seen_tokens.discard(mint)
                    to_remove.append(mint)
                    # Update token_data with fresh MC
                    token_data['usd_market_cap'] = current_mc
                    if await self._should_snipe(token_data):
                        await self._execute_snipe(token_data)
                else:
                    # Move to next recheck interval
                    check_data['current_check'] = current_check + 1
                    check_data['prev_mc'] = current_mc
                    logger.info(f"⏳ [RECHECK {current_check+1}/3] {symbol} - Still {top_holders_share*100:.1f}%, next check in 20s")
                    
                    if current_check + 1 >= len(check_times):
                        logger.info(f"❌ [RECHECK EXHAUSTED] {symbol} - Still concentrated after 3 checks")
                        to_remove.append(mint)
        
        # Clean up processed items
        for mint in to_remove:
            del self.recheck_queue[mint]
        
        # Limit queue size (keep only most recent 50)
        if len(self.recheck_queue) > 50:
            sorted_keys = sorted(self.recheck_queue.keys(), 
                key=lambda m: self.recheck_queue[m].get('check_times', [time.time()])[0] if isinstance(self.recheck_queue[m], dict) else self.recheck_queue[m][1])
            for mint in sorted_keys[:len(self.recheck_queue)-50]:
                del self.recheck_queue[mint]
    
    async def _run_pump_portal(self):
        """Run PumpPortal WebSocket in background."""
        try:
            await self.pump_portal.start()
        except Exception as e:
            logger.error(f"PumpPortal error: {e}")
    
    async def _on_new_token(self, token_data: dict):
        """Callback when PumpPortal detects a new token."""
        mint = token_data.get('mint')
        if not mint or mint in self.seen_tokens:
            return
        
        self.seen_tokens.add(mint)
        
        # Memory Guard: Keep seen_tokens at a reasonable size
        if len(self.seen_tokens) > 5000:
            self.seen_tokens.clear()
        
        # Vet and snipe if passes
        try:
            if await self._should_snipe(token_data):
                await self._execute_snipe(token_data)
        except Exception as e:
            logger.error(f"Snipe evaluation error for {mint[:12]}: {e}")

    async def _should_snipe(self, token_data: dict) -> bool:
        """Mandatory Safety Vetting."""
        mint = token_data.get('mint')
        mc = token_data.get('usd_market_cap', 0)
        score = token_data.get('score', 0)
        
        # A. Basic Filters
        if mc < self.min_mc:
            logger.info(f"⏭️ [SKIP] {token_data.get('symbol')} - Low MC: ${mc:,.0f} (need ${self.min_mc:,.0f}+)")
            return False
        if mc > self.max_mc:
            logger.info(f"⏭️ [SKIP] {token_data.get('symbol')} - High MC: ${mc:,.0f} (max ${self.max_mc:,.0f})")
            return False
        if score < self.min_momentum:
            return False
        
        # B. MOMENTUM CHECKS (Filter stagnant/dumping tokens)
        # 1. Volume/Buyer Spike Check - Ensure positive flow
        try:
            vol_data = await self._get_token_momentum(mint)
            recent_vol = vol_data.get('volume_sol', 0)
            buyer_count = vol_data.get('buyer_count', 0)
            
            MIN_RECENT_VOL = 1.0  # At least 1 SOL volume indicates activity
            MIN_BUYERS = 3  # At least 3 unique buyers
            
            if recent_vol < MIN_RECENT_VOL and buyer_count < MIN_BUYERS:
                logger.info(f"⏭️ [SKIP] {token_data.get('symbol')} - Low momentum (Vol: {recent_vol:.2f} SOL, Buyers: {buyer_count})")
                return False
        except Exception as e:
            logger.debug(f"Momentum check failed for {mint[:8]}: {e}")
            
        # C. Advanced Safety Checks
        # 1. Holder Concentration Check (Relaxed for t=0 tokens per Grok)
        top_holders_share = await self._get_holder_concentration(mint)
        if top_holders_share > self.holder_threshold:
            # Queue for multi-stage recheck if near threshold (could dilute with organic buys)
            if top_holders_share >= 0.95 and mint not in self.recheck_queue:
                # Multi-interval recheck: first check at 20s
                self.recheck_queue[mint] = {
                    'token_data': token_data,
                    'check_times': [time.time() + 20, time.time() + 40, time.time() + 60],
                    'current_check': 0,
                    'prev_mc': mc
                }
                logger.info(f"🔄 [QUEUED] {token_data.get('symbol')} - 100% concentration, will recheck at 20/40/60s")
            else:
                logger.warning(f"🛡️ [SKIP] {token_data.get('symbol')} - High concentration: {top_holders_share*100:.1f}%")
            return False
            
        # 2. Bundle Detection
        is_bundled = await self._is_bundled(mint)
        if is_bundled:
            logger.warning(f"🛡️ [SKIP] {token_data.get('symbol')} - Possible Bundle/Insider launch")
            return False
            
        # 3. Social Presence Check - NOW OPTIONAL per Grok audit (70% of tokens launch without)
        has_socials = await self._check_socials(mint)
        if not has_socials:
            if self.require_socials:
                logger.warning(f"🛡️ [SKIP] {token_data.get('symbol')} - No Socials (Twitter/Telegram)")
                return False
            else:
                logger.info(f"⚠️ [ALERT] {token_data.get('symbol')} - No socials (proceeding anyway)")
                # NOT BLOCKING - just alert
            
        # 5. Dev History Check (Avoid Serial Ruggers)
        is_safe_dev = await self._check_dev_history(mint)
        if not is_safe_dev:
            logger.warning(f"🛡️ [SKIP] {token_data.get('symbol')} - Suspicious Dev History")
            return False

        logger.info(f"🎯 Target Verified: {token_data.get('symbol')} | MC: ${mc:,.0f} | Score: {score}")
        return True

    async def _get_token_momentum(self, mint: str) -> dict:
        """Fetch volume and buyer activity to validate positive momentum."""
        try:
            url = f"https://frontend-api-v3.pump.fun/coins/{mint}"
            resp = requests.get(url, timeout=5, headers={'User-Agent': 'Mozilla/5.0'}).json()
            
            # Extract momentum indicators
            volume_sol = resp.get('virtual_sol_reserves', 0) / 1e9  # Approximate trading volume
            holder_count = resp.get('holder_count', 0)
            
            return {
                'volume_sol': volume_sol,
                'buyer_count': holder_count
            }
        except Exception as e:
            logger.debug(f"Momentum fetch failed for {mint[:8]}: {e}")
            return {'volume_sol': 0, 'buyer_count': 0}

    async def _get_holder_concentration(self, mint: str) -> float:
        """Fetch top 10 holders and return their combined % of supply."""
        try:
            # Use DexTrader's RPC
            payload = {
                "jsonrpc": "2.0", "id": 1,
                "method": "getTokenLargestAccounts",
                "params": [mint]
            }
            resp = requests.post(self.trader.rpc_url, json=payload, timeout=5).json()
            accounts = resp.get('result', {}).get('value', [])
            
            if not accounts: return 1.0 # Fail safe = skip
            
            # Sum up top 10 (excluding bonding curve which usually has ~80% initially)
            # On pump.fun, the bonding curve is always the largest holder until graduation.
            # We skip the largest (bonding curve) and look at the rest of top 10.
            if len(accounts) < 2: return 0.0
            
            total_top_share = sum(int(a['amount']) for a in accounts[1:11])
            total_supply = 1_000_000_000 * (10**9) # Pump.fun fixed supply
            
            return total_top_share / total_supply
        except Exception as e:
            logger.error(f"Error checking holders for {mint[:8]}: {e}")
            return 1.0

    async def _is_bundled(self, mint: str) -> bool:
        """Detect if multiple wallets bought in the exact same block as creator."""
        try:
            payload = {
                "jsonrpc": "2.0", "id": 1,
                "method": "getSignaturesForAddress",
                "params": [mint, {"limit": 10}]
            }
            resp = requests.post(self.trader.rpc_url, json=payload, timeout=5).json()
            sigs = resp.get('result', [])
            
            if len(sigs) < 2: return False
            
            # Count transactions in the same slot (block)
            first_slot = sigs[-1].get('slot') # Creation or earliest tx seen
            insiders = [s for s in sigs if s.get('slot') == first_slot]
            
            if len(insiders) > 5: # More than 5 tx in creation block is suspicious
                return True
                
            return False
        except Exception:
            return False

    async def _check_socials(self, mint: str) -> bool:
        """Check if the token has at least one social link (Twitter/Telegram/Website)."""
        try:
            url = f"https://frontend-api-v3.pump.fun/coins/{mint}"
            resp = requests.get(url, timeout=5).json()
            twitter = resp.get('twitter')
            telegram = resp.get('telegram')
            website = resp.get('website')
            return any([twitter, telegram, website])
        except Exception:
            return False

    async def _check_liquidity_depth(self, mint: str) -> bool:
        """Ensure there is at least 5 SOL in the bonding curve to support trades."""
        try:
            url = f"https://frontend-api-v3.pump.fun/coins/{mint}"
            resp = requests.get(url, timeout=5).json()
            # On pump.fun, 'real_sol_reserves' is the amount currently in the curve.
            # We want at least 5+ SOL to avoid extreme volatility on small buys
            sol_reserve = resp.get('real_sol_reserves', 0) / 1e9
            if sol_reserve < 5.0:
                return False
            return True
        except Exception:
            return False

    async def _check_dev_history(self, mint: str) -> bool:
        """Analyze creator's past launches to identify 'Serial Ruggers'."""
        try:
            # 1. Get creator address
            url = f"https://frontend-api-v3.pump.fun/coins/{mint}"
            resp = requests.get(url, timeout=5).json()
            creator = resp.get('creator')
            if not creator: return False
            
            # 2. Get past coins by this creator
            # Use dedicated history API
            hist_url = f"https://frontend-api-v3.pump.fun/coins/user-created/{creator}?limit=10&offset=0"
            hist = requests.get(hist_url, timeout=5).json()
            
            if not hist or len(hist) < 2: return True # New dev or first coin is neutral
            
            # 3. Analyze success rate
            # If all past coins ended up < $20k MC, it's a serial pump-and-dumper
            failed_coins = 0
            for coin in hist:
                if coin.get('mint') == mint: continue
                if coin.get('usd_market_cap', 0) < 20000:
                    failed_coins += 1
            
            failure_rate = failed_coins / (len(hist) - 1)
            if failure_rate > 0.8: # >80% failure rate is a major red flag
                logger.warning(f"🚩 [RED FLAG] Dev {creator[:8]} failure rate: {failure_rate*100:.0f}%")
                return False
                
            return True
        except Exception:
            return True # Neutral if API fails

    async def _audit_held_positions(self):
        """CRITICAL FIX: Ensure every token we own is actively monitored for exit."""
        try:
            # Faster audit (30s) for Elite Mode
            now = time.time()
            if hasattr(self, '_last_audit_time') and now - self._last_audit_time < 30:
                return
            self._last_audit_time = now

            holdings = await asyncio.to_thread(self.trader.get_all_tokens)
            for mint in holdings:
                if mint not in self.exit_coord.active_monitors:
                    # Found an 'Orphan' token! Start monitoring it immediately.
                    logger.warning(f"🩹 FOUND ORPHAN: {mint[:8]}... recovery exit monitor.")
                    # For orphans, we don't know the entry_mc, so we use current
                    current_mc = await self.exit_coord._get_mc(mint)
                    await self.exit_coord.start_monitoring(
                        mint,
                        entry_mc=current_mc or 15000, 
                        wallet_key=self.wallets.get_main_key()
                    )
        except Exception as e:
            logger.error(f"Audit error: {e}")

    async def _execute_snipe(self, token_data: dict):
        """Launch the buy and pass to exit coordinator."""
        mint = token_data.get('mint')
        symbol = token_data.get('symbol')
        mc = token_data.get('usd_market_cap', 0)
        
        if self.dry_run:
            logger.info(f"🧪 [DRY RUN] Would buy {self.buy_amount} SOL of {symbol} ({mint})")
            await self.alerter.notify(
                f"🧪 **[DRY RUN] TARGET**: {symbol} (${mc:,.0f} MC)\nWould buy {self.buy_amount} SOL\nMint: `{mint[:12]}...`",
                title="🎯 SNIPER DRY RUN",
                color=0x95a5a6  # Grey for dry run
            )
            return


        logger.info(f"💸 SNIPING: Buying {symbol}...")
        
        await self.alerter.notify(
            f"🚀 **SNIPE TARGET**: {symbol} (${mc:,.0f} MC)",
            title="🎯 SNIPER INCOMING",
            color=0x3498db
        )
        
        # Execute Buy with Dynamic Position Sizing
        try:
            # Calculate optimal buy amount from risk manager
            buy_amount = await self.risk_mgr.calculate_buy_amount()
            
            if buy_amount is None:
                logger.info(f"⏸️ Skipping snipe - risk limits reached")
                return
            
            # Check if we already have this position
            if self.risk_mgr.is_position_open(mint):
                logger.info(f"⚠️ Already holding {symbol}, skipping")
                return
                
            logger.info(f"📊 Risk Manager approved: {buy_amount:.4f} SOL")
            
            # Pre-buy balance check
            sol_balance = await asyncio.to_thread(self.trader.get_sol_balance)
            if sol_balance < buy_amount + 0.01:  # Need buy amount + fees
                logger.error(f"❌ INSUFFICIENT SOL: Have {sol_balance:.3f}, need {buy_amount + 0.01:.3f}")
                await self.alerter.notify(
                    f"❌ **INSUFFICIENT SOL**\\nHave: {sol_balance:.3f} SOL\\nNeed: {buy_amount + 0.01:.3f} SOL",
                    title="⚠️ WALLET LOW",
                    color=0xe74c3c,
                    critical=True
                )
                return
            
            # PRE-BUY DUMP CHECK: Validate MC hasn't crashed since vetting
            # Prevents buying into dump tails (common on fast Pump.fun swings)
            try:
                fresh_mc = await self.exit_coord._get_mc(mint)
                if fresh_mc and mc > 0:
                    mc_change = (fresh_mc - mc) / mc
                    if mc_change < -0.10:  # Dropped >10% since vetting
                        logger.warning(f"🚫 DUMP DETECTED: {symbol} dropped {mc_change*100:.0f}% (${mc:,.0f} → ${fresh_mc:,.0f}) - SKIPPING")
                        return
                    elif mc_change < -0.05:  # Dropped 5-10% - warn but proceed
                        logger.info(f"⚠️ Slight dip on {symbol}: {mc_change*100:.1f}% - proceeding cautiously")
                    # Update MC to fresh value for accurate entry tracking
                    mc = fresh_mc
            except Exception as e:
                logger.debug(f"Pre-buy MC check failed: {e} - proceeding anyway")
            
            # Execute the buy
            result = await asyncio.to_thread(
                self.trader.pump_buy, 
                mint, 
                sol_amount=buy_amount
            )
            
            if result and result.get('success'):
                logger.info(f"✅ SNIPE SUCCESS: {symbol}")
                await self.alerter.notify(
                    f"✅ **BOUGHT**: {symbol} ({buy_amount:.4f} SOL)\nTX: {result.get('signature')}",
                    title="💰 SNIPE EXECUTED",
                    color=0x2ecc71,
                    critical=True
                )
                
                # Record position in risk manager with full metadata
                self.risk_mgr.record_position_open(
                    mint, buy_amount, 
                    entry_mc=mc, 
                    wallet_key=self.wallets.get_main_key(),
                    symbol=symbol
                )
                
                # Discord webhook alert on successful buy
                if self.alerter:
                    self.alerter.alert_buy_success(
                        symbol=symbol,
                        mint=mint,
                        amount_sol=buy_amount,
                        entry_mc=mc,
                        tx_sig=result.get('signature')
                    )
                
                # Start Exit Monitor with symbol for better logging
                await self.exit_coord.start_monitoring(
                    mint=mint, 
                    entry_mc=mc, 
                    wallet_key=self.wallets.get_main_key(),
                    symbol=symbol
                )
            else:
                error = result.get('error', 'Unknown Error') if result else "No Result"
                logger.warning(f"❌ SNIPE FAILED: {symbol} - {error}")
                # Discord webhook alert on failed buy
                if self.alerter:
                    self.alerter.alert_buy_failed(symbol, mint, error)
        except Exception as e:
            logger.error(f"❌ Execution error: {e}")

    async def _notify_discord(self, message: str, critical: bool = False):
        """LEGACY: Redirecting to smart alerter."""
        await self.alerter.notify(message, critical=critical)

    def stop(self):
        self.running = False
        logger.info("🛑 Sniper stopping...")

if __name__ == "__main__":
    sniper = MarketSniper(dry_run=False)  # LIVE MODE ENABLED
    asyncio.run(sniper.start())
