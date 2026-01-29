import asyncio
import logging
import os
import time
import requests
from typing import List, Optional, Callable, Dict

logger = logging.getLogger(__name__)

# Import Jupiter for Raydium migration sells
try:
    from jupiter_client import get_jupiter_client, check_token_graduated
    JUPITER_AVAILABLE = True
except ImportError:
    JUPITER_AVAILABLE = False
    logger.warning("Jupiter client not available - Raydium sells disabled")

# Import risk manager for position tracking
try:
    from risk_manager import get_risk_manager
    RISK_MANAGER_AVAILABLE = True
except ImportError:
    RISK_MANAGER_AVAILABLE = False

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
                        # Grok Opt: Momentum Check. If vertical growth, wait.
                        if hasattr(self, '_last_mc') and (mc > self._last_mc * 1.1):
                            logger.info(f"🚀 ROCKET DETECTED! Delaying sell to capture overshoot... (+10% in 5s)")
                        else:
                            logger.info(f"💰 TIER {current_tier_idx+1} HIT! ({multiplier:.2f}x >= {target_mult}x)")
                            # Elite Mode: Adaptive Slippage based on MC
                            current_slippage = 25
                            if mc < 30000: current_slippage = 40
                            elif mc < 60000: current_slippage = 30
                            
                            await self._execute_sell(mint, wallet_key, int(sell_pct * 100), slippage=current_slippage)
                            current_tier_idx += 1
                            if current_tier_idx >= len(self.tiers):
                                return # Fully exited
                
                self._last_mc = mc

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
        """Execute sell with Jupiter fallback for graduated tokens."""
        if not self.dex_trader:
            logger.error("No dex_trader available for sell")
            return
            
        # Pre-check: Don't waste API calls if we have no tokens or dust
        try:
            from solders.keypair import Keypair
            kp = Keypair.from_base58_string(wallet_key)
            wallet_addr = str(kp.pubkey())
            bal_info = self.dex_trader._get_wallet_token_balance(wallet_addr, mint)
            token_balance = bal_info.get('ui_amount', 0) or 0
            token_amount_raw = bal_info.get('amount', 0) or 0
            # Skip if balance is zero or dust (<0.001 tokens)
            if token_balance < 0.001:
                logger.info(f"📌 SKIP SELL: No tokens to sell for {mint[:8]} (balance: {token_balance:.6f})")
                return
        except Exception as e:
            logger.debug(f"Balance pre-check failed for {mint[:8]}: {e}")
            token_amount_raw = 0
        
        # Calculate sell amount based on percentage
        sell_amount = int(token_amount_raw * percentage / 100) if token_amount_raw else 0
        
        # Try Pump.fun sell first
        logger.info(f"💥 SELLING {percentage}% of {mint[:8]} (Slippage: {slippage}%)")
        
        result = await asyncio.to_thread(
            self.dex_trader.pump_sell,
            mint,
            token_amount_pct=percentage,
            payer_key=wallet_key,
            slippage=slippage
        )
        
        if result and result.get('success'):
            logger.info(f"✅ SELL SUCCESS via Pump.fun: {percentage}% of {mint[:8]}")
            # Update risk manager if available and this is a full sell
            if percentage >= 100 and RISK_MANAGER_AVAILABLE:
                try:
                    rm = get_risk_manager()
                    rm.record_position_close(mint)
                except Exception as e:
                    logger.debug(f"Risk manager update failed: {e}")
            return
        
        # Check if token graduated to Raydium - try Jupiter fallback
        pump_error = result.get('error', '') if result else ''
        
        # Detect graduation indicators
        is_graduated = (
            'bonding curve complete' in pump_error.lower() or
            'insufficient liquidity' in pump_error.lower() or
            (JUPITER_AVAILABLE and await check_token_graduated(mint))
        )
        
        if is_graduated and JUPITER_AVAILABLE and sell_amount > 0:
            logger.info(f"🎓 Token {mint[:8]} graduated to Raydium! Trying Jupiter swap...")
            
            try:
                jupiter = get_jupiter_client(wallet_addr)
                success, tx_sig = await jupiter.execute_swap(
                    input_mint=mint,
                    amount=sell_amount,
                    trader=self.dex_trader,
                    slippage_bps=slippage * 100  # Convert % to bps
                )
                
                if success:
                    logger.info(f"✅ SELL SUCCESS via Jupiter: {percentage}% of {mint[:8]} | TX: {tx_sig}")
                    # Update risk manager
                    if percentage >= 100 and RISK_MANAGER_AVAILABLE:
                        try:
                            rm = get_risk_manager()
                            rm.record_position_close(mint)
                        except:
                            pass
                    return
                else:
                    logger.warning(f"⚠️ Jupiter sell also failed for {mint[:8]}")
            except Exception as e:
                logger.error(f"Jupiter swap error: {e}")
        
        # Retry Pump.fun if Jupiter failed or wasn't available
        logger.info(f"💥 Retrying Pump.fun sell for {mint[:8]}...")
        result = await asyncio.to_thread(
            self.dex_trader.pump_sell,
            mint,
            token_amount_pct=percentage,
            payer_key=wallet_key,
            slippage=min(slippage + 10, 50)  # Increase slippage on retry
        )
        
        if result and result.get('success'):
            logger.info(f"✅ SELL SUCCESS on retry: {percentage}% of {mint[:8]}")
            if percentage >= 100 and RISK_MANAGER_AVAILABLE:
                try:
                    rm = get_risk_manager()
                    rm.record_position_close(mint)
                except:
                    pass
        else:
            logger.error(f"❌ SELL FAILED after all attempts: {mint[:8]}")

def get_sniper_exit_coordinator(dex_trader=None):
    global _sniper_coord_instance
    if '_sniper_coord_instance' not in globals():
        globals()['_sniper_coord_instance'] = SniperExitCoordinator(dex_trader)
    return globals()['_sniper_coord_instance']
