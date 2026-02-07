"""
Sniper Exit Coordinator
Manages profit-taking tiers, stop-losses, trailing stops, and timeout sells.
Now with Discord alerts, retroactive timeout, and dynamic profit taking.
"""
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

# Import Discord alerter
try:
    from discord_alerter import get_discord_alerter
    DISCORD_AVAILABLE = True
except ImportError:
    DISCORD_AVAILABLE = False


class SniperExitCoordinator:
    """
    Specialized exit coordinator for sniped tokens.
    Implements multi-stage profit taking, trailing stop-losses, and timeout sells.
    """
    def __init__(self, dex_trader):
        self.dex_trader = dex_trader
        self.active_monitors = {}  # mint -> task
        self.position_data = {}    # mint -> {entry_time, entry_mc, symbol, wallet_key}
        
        # Discord alerter
        self.alerter = get_discord_alerter() if DISCORD_AVAILABLE else None
        
        # Default sniping strategy tiers - STABILITY MODE
        # (multiplier, percentage_of_REMAINING_to_sell)
        self.default_tiers = [
            (1.4, 0.35),   # Sell 35% at 1.4x - lock in quick gains
            (2.0, 0.40),   # Sell 40% of remainder at 2x
            (5.0, 1.0)     # Sell rest at 5x or trailing stop
        ]
        
        # Extended tiers for high-momentum tokens
        self.momentum_tiers = [
            (1.8, 0.25),   # Sell 25% at 1.8x (less aggressive)
            (3.0, 0.40),   # Sell 40% of remainder at 3x
            (7.0, 1.0)     # Sell all at 7x
        ]
        
        # TIGHTER STOP LOSS: -25% flat for stability
        self.stop_loss_early = 0.25   # -25% (was -40%)
        self.stop_loss_normal = 0.25  # -25% (was -35%)
        self.trailing_stop_pct = 0.15 # 15% drop from peak (active after growth)
        
        # FASTER TIMEOUT: Recycle capital quicker
        self.timeout_partial = 2700   # 45 min (was 90) - partial sell if low vol/growth
        self.timeout_full = 4500      # 75 min (was 120) - full exit
        self.timeout_growth_threshold = 1.25  # Must have 25% growth to avoid timeout
        self.partial_timeout_sold = set()  # Track which positions had partial timeout
        
        # Flag for retroactive check (run once on first monitor start)
        self._retroactive_checked = False

    async def _check_retroactive_timeouts(self):
        """On startup, check for any old stagnant positions that should be sold."""
        await asyncio.sleep(10)  # Give time for positions to load
        
        if not RISK_MANAGER_AVAILABLE:
            return
            
        try:
            rm = get_risk_manager()
            positions = rm.get_open_positions()  # Get all open positions
            
            if not positions:
                logger.info("📋 No existing positions to check for timeout")
                return
            
            logger.info(f"📋 Checking {len(positions)} existing positions for stagnation...")
            
            for mint, pos_data in positions.items():
                entry_time = pos_data.get('entry_time', time.time())
                entry_mc = pos_data.get('entry_mc', 0)
                age_seconds = time.time() - entry_time
                age_minutes = age_seconds / 60
                
                # Skip if not old enough
                if age_seconds < self.timeout_partial:  # BUG FIX: was using stale self.timeout
                    continue
                
                # Check current MC
                current_mc = await self._get_mc(mint)
                if not current_mc or not entry_mc:
                    continue
                
                growth = current_mc / entry_mc if entry_mc > 0 else 0
                
                # If stagnant, trigger timeout sell
                if growth < self.timeout_growth_threshold:
                    symbol = pos_data.get('symbol', mint[:8])
                    wallet_key = pos_data.get('wallet_key')
                    
                    if wallet_key:
                        logger.warning(f"⏰ RETROACTIVE TIMEOUT: {symbol} held {age_minutes:.0f}min with only {growth:.2f}x growth")
                        
                        # Alert
                        if self.alerter:
                            self.alerter.alert_timeout_sell(symbol, mint, age_minutes, growth)
                        
                        # Execute sell
                        await self._execute_sell(mint, wallet_key, 100)
                        
        except Exception as e:
            logger.error(f"Retroactive timeout check failed: {e}")

    async def start_monitoring(self, mint: str, entry_mc: float, wallet_key: str, symbol: str = None):
        """Start tracking a sniped position."""
        # Run retroactive check once on first call (event loop is now running)
        if not self._retroactive_checked:
            self._retroactive_checked = True
            asyncio.create_task(self._check_retroactive_timeouts())
        
        if mint in self.active_monitors:
            return
        
        # Store position data for retroactive checks
        self.position_data[mint] = {
            'entry_time': time.time(),
            'entry_mc': entry_mc,
            'symbol': symbol or mint[:8],
            'wallet_key': wallet_key
        }
            
        task = asyncio.create_task(
            self._monitor_loop(mint, entry_mc, wallet_key, symbol)
        )
        self.active_monitors[mint] = task
        
        def cleanup(t):
            if mint in self.active_monitors:
                del self.active_monitors[mint]
            if mint in self.position_data:
                del self.position_data[mint]
        task.add_done_callback(cleanup)

    async def _check_momentum(self, mint: str) -> bool:
        """Check if token has high momentum (worthy of extended tiers)."""
        try:
            url = f"https://frontend-api-v3.pump.fun/coins/{mint}"
            resp = requests.get(url, timeout=5, headers={'User-Agent': 'Mozilla/5.0'}).json()
            
            # Check recent volume and buyer activity
            volume_sol = resp.get('virtual_sol_reserves', 0) / 1e9
            num_buyers = resp.get('holder_count', 0)
            
            # High momentum indicators
            return volume_sol > 5 or num_buyers > 20
        except:
            return False

    async def _monitor_loop(self, mint: str, entry_mc: float, wallet_key: str, symbol: str = None):
        start_time = time.time()
        peak_mc = entry_mc
        current_tier_idx = 0
        symbol = symbol or mint[:8]
        
        # Start with default tiers, may switch to momentum tiers
        current_tiers = self.default_tiers.copy()
        momentum_checked = False
        
        logger.info(f"💎 MONITORING SNIPE: {symbol} | Entry MC: ${entry_mc:,.0f}")
        
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
                
                # Dynamic Tier Adjustment based on volume (check once after 2min)
                if not momentum_checked and elapsed > 120:
                    momentum_checked = True
                    try:
                        url = f"https://frontend-api-v3.pump.fun/coins/{mint}"
                        resp = requests.get(url, timeout=5, headers={'User-Agent': 'Mozilla/5.0'}).json()
                        volume_sol = resp.get('virtual_sol_reserves', 0) / 1e9
                        
                        if volume_sol > 5:  # High volume = let runners run
                            logger.info(f"🚀 HIGH VOLUME ({volume_sol:.1f} SOL) on {symbol}! Using extended tiers (3x/7x/15x)")
                            current_tiers = self.momentum_tiers.copy()
                        else:
                            logger.info(f"📉 Normal volume ({volume_sol:.1f} SOL) on {symbol} - keeping default tiers (2x/5x/10x)")
                    except Exception as e:
                        logger.debug(f"Volume check failed: {e}")

                # 1. Check Tiers (Profit Taking)
                if current_tier_idx < len(current_tiers):
                    target_mult, sell_pct = current_tiers[current_tier_idx]
                    if multiplier >= target_mult:
                        # Momentum check - if vertical growth, wait 5s
                        if 'last_mc' in locals() and (mc > last_mc * 1.1):
                            logger.info(f"🚀 ROCKET DETECTED! Delaying sell to capture overshoot... (+10% in 5s)")
                            await asyncio.sleep(5)
                            continue
                        else:
                            logger.info(f"💰 TIER {current_tier_idx+1} HIT! ({multiplier:.2f}x >= {target_mult}x)")
                            
                            # Adaptive slippage based on MC
                            current_slippage = 25
                            if mc < 30000: current_slippage = 40
                            elif mc < 60000: current_slippage = 30
                            
                            await self._execute_sell(mint, wallet_key, int(sell_pct * 100), slippage=current_slippage)
                            
                            # Alert
                            if self.alerter:
                                self.alerter.alert_sell_tier(symbol, mint, current_tier_idx + 1, multiplier, int(sell_pct * 100))
                            
                            current_tier_idx += 1
                            if current_tier_idx >= len(current_tiers):
                                return  # Fully exited
                
                last_mc = mc

                # 2. Check Initial Stop-Loss (DYNAMIC based on age)
                age_minutes = elapsed / 60
                effective_stop = self.stop_loss_early if age_minutes < 5 else self.stop_loss_normal
                
                if multiplier < (1 - effective_stop):
                    logger.warning(f"🚨 STOP-LOSS HIT: -{effective_stop*100}% on {symbol} (MC: ${mc:,.0f}, Age: {age_minutes:.1f}min)")
                    
                    # Alert
                    if self.alerter:
                        self.alerter.alert_stop_loss(symbol, mint, effective_stop * 100, mc)
                    
                    await self._execute_sell(mint, wallet_key, 100, slippage=50)
                    return

                # 3. Check Trailing Stop Loss (only after 15% growth - STABILITY: was 30%)
                if multiplier > 1.15:
                    # Dynamic trailing - tighter during low volume
                    effective_trailing = self.trailing_stop_pct
                    if await self._check_momentum(mint):
                        effective_trailing = 0.20  # Looser during high momentum
                    
                    stop_price = peak_mc * (1 - effective_trailing)
                    if mc < stop_price:
                        logger.info(f"📉 TRAILING STOP HIT: MC ${mc:,.0f} < ${stop_price:,.0f} (Peak: ${peak_mc:,.0f})")
                        
                        # Alert
                        if self.alerter:
                            self.alerter.alert_trailing_stop(symbol, mint, peak_mc, mc, multiplier)
                        
                        await self._execute_sell(mint, wallet_key, 100, slippage=30)
                        return

                # 4. SMART TIMEOUT: Partial at 90min, Full at 120min
                # Partial timeout: sell 60% if low volume/growth, keep moonshot tail
                if elapsed > self.timeout_partial and mint not in self.partial_timeout_sold:
                    if multiplier < self.timeout_growth_threshold:
                        # Check volume to decide partial vs wait
                        try:
                            url = f"https://frontend-api-v3.pump.fun/coins/{mint}"
                            resp = requests.get(url, timeout=5, headers={'User-Agent': 'Mozilla/5.0'}).json()
                            volume_sol = resp.get('virtual_sol_reserves', 0) / 1e9
                            
                            if volume_sol < 3:  # Low volume = partial sell, keep tail
                                logger.info(f"⏰ PARTIAL TIMEOUT: {symbol} after {elapsed/60:.0f}min (Vol: {volume_sol:.1f} SOL, Growth: {multiplier:.2f}x) - Selling 60%")
                                
                                if self.alerter:
                                    self.alerter.alert_timeout_sell(symbol, mint, elapsed / 60, multiplier, partial=True)
                                
                                await self._execute_sell(mint, wallet_key, 60)
                                self.partial_timeout_sold.add(mint)
                                # Continue monitoring for moonshot
                            else:
                                logger.info(f"⚡ TIMEOUT EXTENDED: {symbol} has volume ({volume_sol:.1f} SOL) - waiting for action")
                        except Exception as e:
                            logger.debug(f"Timeout volume check failed: {e}")
                            # Default to partial sell on error
                            await self._execute_sell(mint, wallet_key, 60)
                            self.partial_timeout_sold.add(mint)
                
                # Full timeout: exit completely after 120min if still stagnant
                if elapsed > self.timeout_full and multiplier < self.timeout_growth_threshold:
                    logger.info(f"⏰ FULL TIMEOUT: Exiting {symbol} after {elapsed/60:.0f}min (only {multiplier:.2f}x growth)")
                    
                    if self.alerter:
                        self.alerter.alert_timeout_sell(symbol, mint, elapsed / 60, multiplier, partial=False)
                    
                    await self._execute_sell(mint, wallet_key, 100)
                    return

                await asyncio.sleep(5)

            except asyncio.CancelledError:
                return
            except Exception as e:
                logger.error(f"Error in snipe monitor {symbol}: {e}")
                await asyncio.sleep(10)

    async def _get_mc(self, mint: str) -> Optional[float]:
        try:
            resp = await asyncio.to_thread(
                requests.get,
                f"https://frontend-api-v3.pump.fun/coins/{mint}",
                timeout=5,
                headers={'User-Agent': 'Mozilla/5.0'}
            )
            return resp.json().get('usd_market_cap', 0)
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
            
            if token_balance < 0.001:
                logger.info(f"📌 SKIP SELL: No tokens to sell for {mint[:8]} (balance: {token_balance:.6f})")
                return
        except Exception as e:
            logger.debug(f"Balance pre-check failed for {mint[:8]}: {e}")
            token_amount_raw = 0
        
        sell_amount = int(token_amount_raw * percentage / 100) if token_amount_raw else 0
        
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
            if percentage >= 100 and RISK_MANAGER_AVAILABLE:
                try:
                    rm = get_risk_manager()
                    rm.record_position_close(mint)
                except Exception as e:
                    logger.debug(f"Risk manager update failed: {e}")
            return
        
        # Check if token graduated - try Jupiter fallback
        pump_error = result.get('error', '') if result else ''
        
        is_graduated = (
            'bonding curve complete' in pump_error.lower() or
            'insufficient liquidity' in pump_error.lower() or
            (JUPITER_AVAILABLE and await check_token_graduated(mint))
        )
        
        if is_graduated:
            symbol = self.position_data.get(mint, {}).get('symbol', mint[:8])
            
            # Alert graduation
            mc = await self._get_mc(mint)
            if self.alerter:
                self.alerter.alert_graduation(symbol, mint, mc or 0)
            
            if JUPITER_AVAILABLE and sell_amount > 0:
                logger.info(f"🎓 Token {mint[:8]} graduated to Raydium! Trying Jupiter swap...")
                
                try:
                    jupiter = get_jupiter_client(wallet_addr)
                    success, tx_sig = await jupiter.execute_swap(
                        input_mint=mint,
                        amount=sell_amount,
                        trader=self.dex_trader,
                        slippage_bps=slippage * 100
                    )
                    
                    if success:
                        logger.info(f"✅ SELL SUCCESS via Jupiter: {percentage}% of {mint[:8]} | TX: {tx_sig}")
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
        
        # Retry Pump.fun with higher slippage
        logger.info(f"💥 Retrying Pump.fun sell for {mint[:8]}...")
        result = await asyncio.to_thread(
            self.dex_trader.pump_sell,
            mint,
            token_amount_pct=percentage,
            payer_key=wallet_key,
            slippage=min(slippage + 10, 50)
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
