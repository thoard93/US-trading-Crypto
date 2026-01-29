"""
Risk Manager - Dynamic Position Sizing & Bankroll Protection
Phase 71: Implements Grok's recommendations for $150 SOL bankroll safety.

Features:
- Buy amount as % of available balance (1-3%)
- Max open positions limit (5)
- Total exposure cap (20%)
- Daily loss limit (-15% = pause)
"""
import asyncio
import logging
import os
import time
from datetime import datetime, date
from typing import Optional

logger = logging.getLogger(__name__)

# ============ RISK CONFIG ============
# Override via env vars for flexibility
# TEMPORARILY RELAXED FOR TESTING (per Grok Jan 29 2026)

BUY_PERCENT_MIN = float(os.getenv('RISK_BUY_PCT_MIN', '0.02'))     # 2% min
BUY_PERCENT_MAX = float(os.getenv('RISK_BUY_PCT_MAX', '0.03'))     # 3% max
MAX_OPEN_POSITIONS = int(os.getenv('RISK_MAX_POSITIONS', '7'))     # Relaxed: 5→7 for testing
MAX_EXPOSURE_PERCENT = float(os.getenv('RISK_MAX_EXPOSURE', '0.35'))  # Relaxed: 30%→35% for more volume
DAILY_LOSS_LIMIT = float(os.getenv('RISK_DAILY_LOSS', '-0.40'))    # Relaxed: -25%→-40% for testing
MIN_BUY_SOL = float(os.getenv('RISK_MIN_BUY', '0.05'))             # Min 0.05 SOL
MIN_BALANCE_RESERVE = float(os.getenv('RISK_RESERVE', '0.1'))      # Keep 0.1 SOL for fees

# ============ STATE TRACKING ============
_daily_pnl_cache = {}  # date -> initial_balance
_open_positions = {}   # mint -> {entry_sol, tokens, entry_time}


class RiskManager:
    """Manages position sizing and risk limits for the sniper."""
    
    def __init__(self, trader=None):
        self.trader = trader
        self._daily_initial_balance = None
        self._today = None
        
    async def get_wallet_balance(self) -> float:
        """Get current SOL balance from wallet."""
        if self.trader:
            try:
                # DexTrader.get_sol_balance is SYNC, not async!
                balance = self.trader.get_sol_balance()
                return balance
            except Exception as e:
                logger.error(f"Failed to get wallet balance: {e}")
                return 0.0
        return 0.0
    
    def _reset_daily_if_needed(self, current_balance: float):
        """Reset daily tracking at midnight."""
        today = date.today().isoformat()
        if self._today != today:
            self._today = today
            self._daily_initial_balance = current_balance
            logger.info(f"📅 New day! Initial balance: {current_balance:.4f} SOL")
    
    async def check_daily_loss_limit(self) -> bool:
        """
        Check if daily loss limit has been hit.
        Returns True if trading is allowed, False if paused.
        """
        current_balance = await self.get_wallet_balance()
        if current_balance <= 0:
            return False
            
        self._reset_daily_if_needed(current_balance)
        
        if self._daily_initial_balance is None:
            self._daily_initial_balance = current_balance
            return True
        
        # Calculate daily PnL
        pnl_pct = (current_balance - self._daily_initial_balance) / self._daily_initial_balance
        
        if pnl_pct <= DAILY_LOSS_LIMIT:
            logger.warning(f"🛑 DAILY LOSS LIMIT HIT! PnL: {pnl_pct*100:.1f}% (limit: {DAILY_LOSS_LIMIT*100:.0f}%)")
            logger.warning(f"   Started: {self._daily_initial_balance:.4f} SOL, Now: {current_balance:.4f} SOL")
            return False
        
        return True
    
    def get_open_position_count(self) -> int:
        """Get number of currently open positions."""
        return len(_open_positions)
    
    def get_total_exposure(self) -> float:
        """Get total SOL currently in open positions."""
        return sum(pos.get('entry_sol', 0) for pos in _open_positions.values())
    
    def is_position_open(self, mint: str) -> bool:
        """Check if we already have a position in this token."""
        return mint in _open_positions
    
    async def calculate_buy_amount(self) -> Optional[float]:
        """
        Calculate optimal buy amount based on:
        - Current balance
        - Number of open positions
        - Total exposure
        - Daily loss status
        
        Returns SOL amount to buy, or None if should skip.
        """
        # Check daily loss limit first
        if not await self.check_daily_loss_limit():
            logger.info("⏸️ Trading paused due to daily loss limit")
            return None
        
        # Check max positions
        open_count = self.get_open_position_count()
        if open_count >= MAX_OPEN_POSITIONS:
            logger.info(f"📊 Max positions reached ({open_count}/{MAX_OPEN_POSITIONS})")
            return None
        
        # Get available balance
        balance = await self.get_wallet_balance()
        exposure = self.get_total_exposure()
        available = balance - exposure - MIN_BALANCE_RESERVE
        
        logger.debug(f"Balance: {balance:.4f}, Exposure: {exposure:.4f}, Available: {available:.4f}")
        
        if available < MIN_BUY_SOL:
            logger.info(f"💰 Insufficient available balance: {available:.4f} SOL < {MIN_BUY_SOL}")
            return None
        
        # Check total exposure limit
        max_allowed_exposure = balance * MAX_EXPOSURE_PERCENT
        remaining_exposure = max_allowed_exposure - exposure
        
        if remaining_exposure < MIN_BUY_SOL:
            logger.info(f"📈 Exposure limit reached ({exposure:.4f}/{max_allowed_exposure:.4f} SOL)")
            return None
        
        # Calculate buy amount (2-3% of available)
        import random
        buy_pct = BUY_PERCENT_MIN + random.random() * (BUY_PERCENT_MAX - BUY_PERCENT_MIN)
        amount = available * buy_pct
        
        # Cap at remaining exposure allowance
        amount = min(amount, remaining_exposure)
        
        # Enforce minimum
        if amount < MIN_BUY_SOL:
            amount = MIN_BUY_SOL
        
        # Round to 4 decimals
        amount = round(amount, 4)
        
        logger.info(f"📊 Calculated buy: {amount:.4f} SOL ({buy_pct*100:.1f}% of {available:.4f} available)")
        
        return amount
    
    def record_position_open(self, mint: str, entry_sol: float, tokens: float = 0):
        """Record a new open position."""
        _open_positions[mint] = {
            'entry_sol': entry_sol,
            'tokens': tokens,
            'entry_time': time.time()
        }
        logger.info(f"📝 Recorded position: {mint[:12]}... | {entry_sol:.4f} SOL | {len(_open_positions)} open")
    
    def record_position_close(self, mint: str, exit_sol: float = 0):
        """Record position close and calculate PnL."""
        if mint in _open_positions:
            pos = _open_positions.pop(mint)
            entry = pos.get('entry_sol', 0)
            pnl = exit_sol - entry
            pnl_pct = (pnl / entry * 100) if entry > 0 else 0
            hold_time = time.time() - pos.get('entry_time', time.time())
            
            logger.info(f"📤 Closed position: {mint[:12]}... | PnL: {pnl:+.4f} SOL ({pnl_pct:+.1f}%) | Held: {hold_time/60:.1f}m")
            return pnl
        return 0
    
    def get_status(self) -> dict:
        """Get current risk status for monitoring."""
        return {
            'open_positions': self.get_open_position_count(),
            'max_positions': MAX_OPEN_POSITIONS,
            'total_exposure_sol': self.get_total_exposure(),
            'max_exposure_pct': MAX_EXPOSURE_PERCENT * 100,
            'daily_loss_limit_pct': DAILY_LOSS_LIMIT * 100,
            'buy_range_pct': f"{BUY_PERCENT_MIN*100:.0f}-{BUY_PERCENT_MAX*100:.0f}%",
            'positions': list(_open_positions.keys())
        }


# Singleton instance
_risk_manager = None

def get_risk_manager(trader=None) -> RiskManager:
    """Get or create singleton risk manager."""
    global _risk_manager
    if _risk_manager is None:
        _risk_manager = RiskManager(trader)
    elif trader and not _risk_manager.trader:
        _risk_manager.trader = trader
    return _risk_manager


# Test script
if __name__ == "__main__":
    import asyncio
    logging.basicConfig(level=logging.INFO)
    
    async def test():
        rm = RiskManager()
        print("Risk Status:", rm.get_status())
        
        # Simulate positions
        rm.record_position_open("test_mint_1", 0.1, 1000000)
        rm.record_position_open("test_mint_2", 0.15, 2000000)
        print("After 2 positions:", rm.get_status())
        
        rm.record_position_close("test_mint_1", 0.2)  # Profit
        print("After closing 1:", rm.get_status())
    
    asyncio.run(test())
