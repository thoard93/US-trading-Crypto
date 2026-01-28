import asyncio
import os
import logging
import json
import time
from datetime import datetime
from typing import Dict, List, Optional

# Core imports
import sys
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from dex_trader import DexTrader
from trend_hunter import TrendHunter
from movers_tracker import get_movers_tracker
from sniper_exit_coordinator import get_sniper_exit_coordinator
from wallet_manager import WalletManager

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
        self.hunter = TrendHunter()
        self.tracker = get_movers_tracker()
        self.wallets = WalletManager()
        self.exit_coord = get_sniper_exit_coordinator(self.trader)
        
        # Strategy Config
        self.min_mc = float(os.getenv('SNIPER_MIN_MC', '15000'))
        self.max_mc = float(os.getenv('SNIPER_MAX_MC', '60000'))
        self.min_momentum = float(os.getenv('SNIPER_MIN_MOMENTUM', '60'))
        self.buy_amount = float(os.getenv('SNIPER_BUY_SOL', '0.1'))
        
        # Smart Alerter
        self.alerter = DiscordAlerter(os.getenv('DISCORD_ALERTS_CHANNEL'))
        
        # Internal State
        self.active_positions = {} # mint -> position_data
        self.seen_tokens = set()
        self.running = False

    async def start(self):
        """Main loop for the sniper."""
        logger.info(f"🚀 Sniper starting... Mode: {'DRY RUN' if self.dry_run else 'LIVE'}")
        self.running = True
        
        # Ensure TrendHunter WebSocket is active
        self.hunter.get_trending_keywords(limit=1) 
        
        while self.running:
            try:
                # 0. Orphan Audit: Ensure any tokens held are being monitored
                await self._audit_held_positions()

                # 1. Discovery Phase (Free/Low-cost)
                tokens = await self.tracker.fetch_movers(limit=20)
                
                for token in tokens:
                    mint = token.get('mint')
                    if not mint or mint in self.seen_tokens:
                        continue
                        
                    # 2. Vetting Phase
                    if await self._should_snipe(token):
                        await self._execute_snipe(token)
                    
                    self.seen_tokens.add(mint)
                    # Memory Guard: Keep seen_tokens at a reasonable size
                    if len(self.seen_tokens) > 5000:
                        self.seen_tokens.clear() # Refresh every 5000 tokens
                
                await asyncio.sleep(5)
                
            except Exception as e:
                logger.error(f"❌ Sniper loop error: {e}")
                await asyncio.sleep(5)

    async def _should_snipe(self, token_data: dict) -> bool:
        """Mandatory Safety Vetting."""
        mint = token_data.get('mint')
        mc = token_data.get('usd_market_cap', 0)
        score = token_data.get('score', 0)
        
        # A. Basic Filters
        if mc < self.min_mc or mc > self.max_mc:
            return False
        if score < self.min_momentum:
            return False
            
        # B. Advanced Safety Checks
        # 1. Holder Concentration Check
        top_holders_share = await self._get_holder_concentration(mint)
        if top_holders_share > 0.30: # >30% in top 10 is risky
            logger.warning(f"🛡️ [SKIP] {token_data.get('symbol')} - High concentration: {top_holders_share*100:.1f}%")
            return False
            
        # 2. Bundle Detection
        is_bundled = await self._is_bundled(mint)
        if is_bundled:
            logger.warning(f"🛡️ [SKIP] {token_data.get('symbol')} - Possible Bundle/Insider launch")
            return False
            
        # 3. Social Presence Check (Avoid "Ghost" tokens)
        has_socials = await self._check_socials(mint)
        if not has_socials:
            logger.warning(f"🛡️ [SKIP] {token_data.get('symbol')} - No Socials (Twitter/Telegram)")
            return False
            
        # 5. Dev History Check (Avoid Serial Ruggers)
        is_safe_dev = await self._check_dev_history(mint)
        if not is_safe_dev:
            logger.warning(f"🛡️ [SKIP] {token_data.get('symbol')} - Suspicious Dev History")
            return False

        logger.info(f"🎯 Target Verified: {token_data.get('symbol')} | MC: ${mc:,.0f} | Score: {score}")
        return True

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
            # Only audit every 60 seconds to save RPC credits
            now = time.time()
            if hasattr(self, '_last_audit_time') and now - self._last_audit_time < 60:
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
            return

        logger.info(f"💸 SNIPING: Buying {self.buy_amount} SOL of {symbol}...")
        
        await self.alerter.notify(
            f"🚀 **SNIPE TARGET**: {symbol} (${mc:,.0f} MC)\nBuying with {self.buy_amount} SOL",
            title="🎯 SNIPER INCOMING",
            color=0x3498db
        )
        
        # Execute Buy
        try:
            # We use the primary wallet for sniping
            result = await asyncio.to_thread(
                self.trader.pump_buy, 
                mint, 
                sol_amount=self.buy_amount
            )
            
            if result and result.get('success'):
                logger.info(f"✅ SNIPE SUCCESS: {symbol}")
                await self.alerter.notify(
                    f"✅ **BOUGHT**: {symbol}\nTX: {result.get('signature')}",
                    title="💰 SNIPE EXECUTED",
                    color=0x2ecc71,
                    critical=True
                )
                
                # Start Exit Monitor
                await self.exit_coord.start_monitoring(
                    mint, 
                    entry_mc=mc, 
                    wallet_key=self.wallets.get_main_key()
                )
            else:
                error = result.get('error', 'Unknown Error') if result else "No Result"
                logger.warning(f"❌ SNIPE FAILED: {symbol} - {error}")
                await self.alerter.notify(
                    f"❌ **FAILED**: {symbol}\nReason: {error}",
                    title="⚠️ SNIPE ERROR",
                    color=0xe74c3c,
                    critical=True
                )
        except Exception as e:
            logger.error(f"❌ Execution error: {e}")

    async def _notify_discord(self, message: str, critical: bool = False):
        """LEGACY: Redirecting to smart alerter."""
        await self.alerter.notify(message, critical=critical)

    def stop(self):
        self.running = False
        logger.info("🛑 Sniper stopping...")

if __name__ == "__main__":
    sniper = MarketSniper(dry_run=True)
    asyncio.run(sniper.start())
