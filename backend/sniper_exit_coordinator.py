import asyncio
import logging
import os
import time
import requests
from typing import List, Optional, Callable, Dict

logger = logging.getLogger(__name__)

class SniperExitCoordinator:
    """
    Specialized exit coordinator for sniped tokens.
    Implements multi-stage profit taking and trailing stop-losses.
    """
    def __init__(self, dex_trader):
        self.dex_trader = dex_trader
        self.active_monitors = {} # mint -> task
        
        # Default sniping strategy tiers
        # (multiplier, percentage_of_REMAINING_to_sell)
        self.tiers = [
            (2.0, 0.50),  # Sell 50% at 2x (Initial money back)
            (5.0, 0.50),  # Sell 50% of remainder at 5x
            (10.0, 1.0)   # Sell all at 10x OR let trailing stop handle it
        ]
        self.stop_loss_pct = 0.25 # Initial hard stop-loss (25% drop from entry)
        self.trailing_stop_pct = 0.15 # 15% drop from peak (active after growth)
        self.timeout = 600 # 10 minute timeout

    async def start_monitoring(self, mint: str, entry_mc: float, wallet_key: str):
        """Start tracking a sniped position."""
        if mint in self.active_monitors:
            return
            
        task = asyncio.create_task(
            self._monitor_loop(mint, entry_mc, wallet_key)
        )
        self.active_monitors[mint] = task
        
        def cleanup(t):
            if mint in self.active_monitors:
                del self.active_monitors[mint]
        task.add_done_callback(cleanup)

    async def _monitor_loop(self, mint: str, entry_mc: float, wallet_key: str):
        start_time = time.time()
        peak_mc = entry_mc
        current_tier_idx = 0
        
        logger.info(f"💎 MONITORING SNIPE: {mint[:8]} | Entry MC: ${entry_mc:,.0f}")
        
        while True:
            try:
                mc = await self._get_mc(mint)
                if not mc:
                    await asyncio.sleep(10)
                    continue
                
                if mc > peak_mc:
                    peak_mc = mc
                
                elapsed = time.time() - start_time
                multiplier = mc / entry_mc
                
                # logger.info(f"📊 [{mint[:8]}] MC: ${mc:,.0f} ({multiplier:.2f}x) | Peak: ${peak_mc:,.0f} | {elapsed:.0f}s")

                # 1. Check Tiers (Profit Taking)
                if current_tier_idx < len(self.tiers):
                    target_mult, sell_pct = self.tiers[current_tier_idx]
                    if multiplier >= target_mult:
                        logger.info(f"💰 TIER {current_tier_idx+1} HIT! ({multiplier:.2f}x >= {target_mult}x)")
                        await self._execute_sell(mint, wallet_key, int(sell_pct * 100))
                        current_tier_idx += 1
                        if current_tier_idx >= len(self.tiers):
                            return # Fully exited

                # 2. Check Initial Stop-Loss
                if multiplier < (1 - self.stop_loss_pct):
                    logger.warning(f"🚨 STOP-LOSS HIT: -{self.stop_loss_pct*100}% on {mint[:8]} (MC: ${mc:,.0f})")
                    await self._execute_sell(mint, wallet_key, 100, slippage=50) # Aggressive slippage for stop loss
                    return

                # 3. Check Trailing Stop Loss
                # Only active after at least 30% growth to avoid instant noise exit
                if multiplier > 1.3:
                    stop_price = peak_mc * (1 - self.trailing_stop_pct)
                    if mc < stop_price:
                        logger.info(f"📉 TRAILING STOP HIT: MC ${mc:,.0f} < ${stop_price:,.0f} (Peak: ${peak_mc:,.0f})")
                        await self._execute_sell(mint, wallet_key, 100, slippage=30)
                        return

                # 4. Check Timeout
                if elapsed > self.timeout:
                    logger.info(f"⏰ SNIPE TIMEOUT: Exiting {mint[:8]} after 10min")
                    await self._execute_sell(mint, wallet_key, 100)
                    return

                await asyncio.sleep(5) # Fast check (5s) for trailing stops

            except asyncio.CancelledError:
                return
            except Exception as e:
                logger.error(f"Error in snipe monitor {mint[:8]}: {e}")
                await asyncio.sleep(10)

    async def _get_mc(self, mint: str) -> Optional[float]:
        try:
            url = f"https://frontend-api-v3.pump.fun/coins/{mint}"
            resp = requests.get(url, timeout=5, headers={'User-Agent': 'Mozilla/5.0'}).json()
            return resp.get('usd_market_cap', 0)
        except:
            return None

    async def _execute_sell(self, mint: str, wallet_key: str, percentage: int, slippage: int = 25):
        if self.dex_trader:
            logger.info(f"💥 SELLING {percentage}% of {mint[:8]} (Slippage: {slippage}%)...")
            # Use thread to avoid blocking loop
            result = await asyncio.to_thread(
                self.dex_trader.pump_sell,
                mint,
                token_amount_pct=percentage,
                payer_key=wallet_key
            )
            if result and result.get('success'):
                logger.info(f"✅ SELL SUCCESS: {percentage}% of {mint[:8]}")
            else:
                logger.warning(f"⚠️ SELL FAILED: {result.get('error')}")

def get_sniper_exit_coordinator(dex_trader=None):
    global _sniper_coord_instance
    if '_sniper_coord_instance' not in globals():
        globals()['_sniper_coord_instance'] = SniperExitCoordinator(dex_trader)
    return globals()['_sniper_coord_instance']
