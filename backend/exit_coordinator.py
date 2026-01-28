"""
Exit Coordinator - Monitors token MC and triggers coordinated dumps.
Phase 70: Swarm Strategy v1 - Hold and dump at target MC.
"""
import asyncio
import logging
import os
import time
import requests
from datetime import datetime
from typing import List, Optional, Callable

logger = logging.getLogger(__name__)

class ExitCoordinator:
    """
    Monitors launched tokens and coordinates swarm exits.
    
    Strategy:
    1. All support wallets buy at launch
    2. Monitor MC every 30s
    3. When MC hits target OR timeout, dump all positions
    """
    
    def __init__(self, dex_trader=None):
        self.dex_trader = dex_trader
        self.logger = logging.getLogger(__name__)
        
        # Configuration from env
        self.target_mc = float(os.getenv('SWARM_EXIT_MC', '25000'))
        self.exit_timeout = int(os.getenv('SWARM_EXIT_TIMEOUT', '600'))  # 10 min
        self.poll_interval = 30  # Check MC every 30s
        
        # Active monitors: mint -> task
        self.active_monitors = {}
        
    async def start_exit_monitor(
        self, 
        mint: str, 
        wallet_keys: List[str],
        callback: Optional[Callable] = None
    ):
        """
        Start monitoring a token for exit conditions.
        
        Args:
            mint: Token mint address
            wallet_keys: List of wallet private keys that hold positions
            callback: Optional async callback for status updates
        """
        if mint in self.active_monitors:
            self.logger.warning(f"Already monitoring {mint[:8]}...")
            return
        
        self.logger.info(f"🎯 Starting exit monitor for {mint[:8]}... Target: ${self.target_mc:,.0f} MC")
        
        task = asyncio.create_task(
            self._monitor_loop(mint, wallet_keys, callback)
        )
        self.active_monitors[mint] = task
        
        # Cleanup when done
        def cleanup(t):
            if mint in self.active_monitors:
                del self.active_monitors[mint]
                self.logger.info(f"🧹 Exit monitor cleaned up for {mint[:8]}...")
        
        task.add_done_callback(cleanup)
        
    async def _monitor_loop(
        self, 
        mint: str, 
        wallet_keys: List[str],
        callback: Optional[Callable]
    ):
        """Main monitoring loop - checks MC and triggers exit."""
        start_time = time.time()
        check_count = 0
        peak_mc = 0
        
        while True:
            try:
                elapsed = time.time() - start_time
                check_count += 1
                
                # Get current MC
                mc = await self._get_mc(mint)
                if mc and mc > peak_mc:
                    peak_mc = mc
                
                self.logger.info(f"📊 [{mint[:8]}] MC: ${mc:,.0f} | Peak: ${peak_mc:,.0f} | {elapsed:.0f}s elapsed")
                
                # Check exit conditions
                should_exit = False
                exit_reason = ""
                
                # Condition 1: Hit target MC
                if mc and mc >= self.target_mc:
                    should_exit = True
                    exit_reason = f"🎯 Target MC hit! ${mc:,.0f} >= ${self.target_mc:,.0f}"
                
                # Condition 2: Timeout
                elif elapsed >= self.exit_timeout:
                    should_exit = True
                    exit_reason = f"⏰ Timeout after {elapsed:.0f}s (MC: ${mc:,.0f})"
                
                # Condition 3: MC dropped significantly from peak (stop-loss)
                elif peak_mc > 5000 and mc and mc < (peak_mc * 0.5):
                    should_exit = True
                    exit_reason = f"📉 Stop-loss! MC dropped 50% from peak (${peak_mc:,.0f} -> ${mc:,.0f})"
                
                if should_exit:
                    self.logger.info(f"🚨 EXIT TRIGGERED: {exit_reason}")
                    if callback:
                        await callback(f"🚨 EXIT: {exit_reason}")
                    
                    # Execute coordinated dump
                    await self._execute_dump(mint, wallet_keys, callback)
                    return
                
                # Wait before next check
                await asyncio.sleep(self.poll_interval)
                
            except asyncio.CancelledError:
                self.logger.info(f"❌ Monitor cancelled for {mint[:8]}")
                return
            except Exception as e:
                self.logger.error(f"Monitor error for {mint[:8]}: {e}")
                await asyncio.sleep(10)  # Brief pause on error
    
    async def _get_mc(self, mint: str) -> Optional[float]:
        """Fetch current market cap from pump.fun."""
        try:
            url = f"https://frontend-api-v3.pump.fun/coins/{mint}"
            
            loop = asyncio.get_event_loop()
            resp = await loop.run_in_executor(
                None,
                lambda: requests.get(url, timeout=10, headers={
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                })
            )
            
            if resp.status_code == 200:
                data = resp.json()
                return data.get('usd_market_cap', 0)
            
        except Exception as e:
            self.logger.debug(f"MC fetch error: {e}")
        
        return None
    
    async def _execute_dump(
        self, 
        mint: str, 
        wallet_keys: List[str],
        callback: Optional[Callable]
    ):
        """Execute coordinated sell from all wallets."""
        if not self.dex_trader:
            self.logger.error("No DexTrader available for dump!")
            return
        
        self.logger.info(f"💥 EXECUTING SWARM DUMP: {len(wallet_keys)} wallets selling {mint[:8]}...")
        
        if callback:
            await callback(f"💥 Dumping from {len(wallet_keys)} wallets...")
        
        # Sell from all wallets in parallel
        tasks = []
        for i, key in enumerate(wallet_keys):
            label = f"W{i+1}"
            self.logger.info(f"💰 {label} selling all {mint[:8]}...")
            
            # Sell 100% of position
            task = asyncio.create_task(
                asyncio.to_thread(
                    self.dex_trader.pump_sell,
                    mint,
                    percentage=100,
                    payer_key=key
                )
            )
            tasks.append((label, task))
        
        # Wait for all sells to complete
        results = []
        for label, task in tasks:
            try:
                result = await task
                if result and not result.get('error'):
                    self.logger.info(f"✅ {label} sold successfully")
                    results.append(('success', label))
                else:
                    error = result.get('error', 'Unknown') if result else 'No result'
                    self.logger.warning(f"⚠️ {label} sell failed: {error}")
                    results.append(('failed', label))
            except Exception as e:
                self.logger.error(f"❌ {label} sell error: {e}")
                results.append(('error', label))
        
        # Summary
        success_count = sum(1 for r in results if r[0] == 'success')
        if callback:
            await callback(f"✅ Dump complete: {success_count}/{len(wallet_keys)} wallets sold")
        
        self.logger.info(f"🏁 DUMP COMPLETE: {success_count}/{len(wallet_keys)} successful")
    
    def cancel_monitor(self, mint: str):
        """Cancel monitoring for a specific token."""
        if mint in self.active_monitors:
            self.active_monitors[mint].cancel()
            return True
        return False
    
    def get_active_monitors(self) -> List[str]:
        """Get list of currently monitored mints."""
        return list(self.active_monitors.keys())


# Singleton instance
_coordinator_instance = None

def get_exit_coordinator(dex_trader=None):
    """Get or create the singleton exit coordinator."""
    global _coordinator_instance
    if _coordinator_instance is None:
        _coordinator_instance = ExitCoordinator(dex_trader)
    elif dex_trader and not _coordinator_instance.dex_trader:
        _coordinator_instance.dex_trader = dex_trader
    return _coordinator_instance


# Test
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    coord = ExitCoordinator()
    print(f"Exit Coordinator initialized")
    print(f"  Target MC: ${coord.target_mc:,.0f}")
    print(f"  Timeout: {coord.exit_timeout}s")
    print(f"  Poll interval: {coord.poll_interval}s")
