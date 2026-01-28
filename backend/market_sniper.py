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
        
        # Discord Channel
        self.discord_channel_id = os.getenv('DISCORD_ALERTS_CHANNEL')
        
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
                
                await asyncio.sleep(5) # Faster polling for momentum
                
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
            
        # 3. Creator Check (Simple version)
        # TODO: integrate whale_wallets history
        
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

    async def _execute_snipe(self, token_data: dict):
        """Launch the buy and pass to exit coordinator."""
        mint = token_data.get('mint')
        symbol = token_data.get('symbol')
        mc = token_data.get('usd_market_cap', 0)
        
        if self.dry_run:
            logger.info(f"🧪 [DRY RUN] Would buy {self.buy_amount} SOL of {symbol} ({mint})")
            return

        logger.info(f"💸 SNIPING: Buying {self.buy_amount} SOL of {symbol}...")
        
        # Notify Discord
        await self._notify_discord(f"💸 **SNIPING**: {symbol} (${mc:,.0f} MC) with {self.buy_amount} SOL")
        
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
                await self._notify_discord(f"✅ **BOUGHT**: {symbol} | TX: {result.get('signature')}")
                
                # Start Exit Monitor
                await self.exit_coord.start_monitoring(
                    mint, 
                    entry_mc=mc, 
                    wallet_key=self.wallets.get_main_key()
                )
            else:
                error = result.get('error', 'Unknown Error') if result else "No Result"
                logger.warning(f"❌ SNIPE FAILED: {symbol} - {error}")
                await self._notify_discord(f"❌ **FAILED**: {symbol} - {error}")
        except Exception as e:
            logger.error(f"❌ Execution error: {e}")

    async def _notify_discord(self, message: str):
        """Send status updates to Discord if channel is configured."""
        if not self.discord_channel_id:
            return
            
        try:
            from bot import get_discord_client
            client = get_discord_client()
            if client:
                channel = client.get_channel(int(self.discord_channel_id))
                if channel:
                    await channel.send(message)
        except Exception as e:
            logger.debug(f"Discord notify error: {e}")

    def stop(self):
        self.running = False
        logger.info("🛑 Sniper stopping...")

if __name__ == "__main__":
    sniper = MarketSniper(dry_run=True)
    asyncio.run(sniper.start())
