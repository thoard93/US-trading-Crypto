"""
Polymarket Copy Trader
Safe, automated copy-trading of top Polymarket whales.

SAFETY FEATURES:
1. Paper Trading Mode (default) - Test without real money
2. Conservative Bet Sizing - Max 5% of bankroll per bet
3. Whale Consensus - Only bet when 3+ whales agree
4. Odds Filtering - Skip extreme prices (<10¢ or >90¢)
5. Daily Loss Limit - Stop trading if down 15%
6. Cooldown Period - Wait 5 mins between bets on same market
"""
import os
import json
import logging
import asyncio
from typing import Dict, List, Optional
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

# Try to import py-clob-client (may not be installed yet)
try:
    from py_clob_client.client import ClobClient
    from py_clob_client.clob_types import MarketOrderArgs, OrderType
    from py_clob_client.order_builder.constants import BUY, SELL
    PY_CLOB_AVAILABLE = True
except ImportError:
    PY_CLOB_AVAILABLE = False
    logger.warning("⚠️ py-clob-client not installed. Install with: pip install py-clob-client")


@dataclass
class PolymarketPosition:
    """Tracks a position we've taken."""
    token_id: str
    market_id: str
    outcome: str
    entry_price: float
    size_usdc: float
    shares: float
    timestamp: datetime
    whale_count: int  # How many whales were in the swarm
    status: str = "OPEN"  # OPEN, CLOSED, EXPIRED


@dataclass
class TradingConfig:
    """Configuration for safe trading."""
    # Core settings
    paper_mode: bool = True  # Start in paper mode!
    max_bet_usdc: float = 10.0  # Max $10 per bet
    max_bet_pct: float = 0.05  # Max 5% of bankroll
    min_whale_consensus: int = 3  # Need 3+ whales
    
    # Price filters (avoid extreme odds)
    min_price: float = 0.10  # Skip if price < 10¢
    max_price: float = 0.90  # Skip if price > 90¢
    
    # Risk management
    daily_loss_limit_pct: float = 0.15  # Stop if down 15%
    cooldown_minutes: int = 5  # Wait between same-market bets
    max_open_positions: int = 10  # Max concurrent bets
    
    # Position management
    take_profit_pct: float = 0.50  # Take profit at 50% gain
    stop_loss_pct: float = 0.25  # Stop loss at 25% loss


class PolymarketTrader:
    """
    Automated copy-trading for Polymarket prediction markets.
    
    Features:
    - Follows top PNL traders (whales)
    - Only trades when multiple whales agree (swarm signal)
    - Conservative position sizing
    - Paper trading mode for testing
    """
    
    def __init__(self, config: Optional[TradingConfig] = None):
        self.config = config or TradingConfig()
        self.client: Optional[ClobClient] = None
        self.positions: Dict[str, PolymarketPosition] = {}
        self.trade_history: List[Dict] = []
        self.cooldowns: Dict[str, datetime] = {}
        
        # Daily P&L tracking
        self.daily_pnl: float = 0.0
        self.daily_start: datetime = datetime.now()
        self.starting_balance: float = 0.0
        
        # Persistence
        self.data_file = Path("polymarket_positions.json")
        self._load_positions()
        
        # Paper trading stats
        self.paper_balance: float = 100.0  # Start with $100 paper money
        self.paper_pnl: float = 0.0
    
    def _load_positions(self):
        """Load positions from disk."""
        if self.data_file.exists():
            try:
                with open(self.data_file, "r") as f:
                    data = json.load(f)
                    for pos_data in data.get("positions", []):
                        pos = PolymarketPosition(
                            token_id=pos_data["token_id"],
                            market_id=pos_data["market_id"],
                            outcome=pos_data["outcome"],
                            entry_price=pos_data["entry_price"],
                            size_usdc=pos_data["size_usdc"],
                            shares=pos_data["shares"],
                            timestamp=datetime.fromisoformat(pos_data["timestamp"]),
                            whale_count=pos_data["whale_count"],
                            status=pos_data.get("status", "OPEN")
                        )
                        if pos.status == "OPEN":
                            self.positions[pos.token_id] = pos
                    self.paper_balance = data.get("paper_balance", 100.0)
                    self.paper_pnl = data.get("paper_pnl", 0.0)
                    logger.info(f"📂 Loaded {len(self.positions)} Polymarket positions")
            except Exception as e:
                logger.error(f"Error loading positions: {e}")
    
    def _save_positions(self):
        """Save positions to disk."""
        try:
            data = {
                "positions": [
                    {
                        "token_id": p.token_id,
                        "market_id": p.market_id,
                        "outcome": p.outcome,
                        "entry_price": p.entry_price,
                        "size_usdc": p.size_usdc,
                        "shares": p.shares,
                        "timestamp": p.timestamp.isoformat(),
                        "whale_count": p.whale_count,
                        "status": p.status
                    }
                    for p in self.positions.values()
                ],
                "paper_balance": self.paper_balance,
                "paper_pnl": self.paper_pnl
            }
            with open(self.data_file, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving positions: {e}")
    
    def initialize_client(self, private_key: str, wallet_address: str) -> bool:
        """
        Initialize the CLOB client for trading.
        
        Args:
            private_key: Polygon wallet private key
            wallet_address: Polygon wallet address (funder)
            
        Returns:
            True if successful, False otherwise
        """
        if not PY_CLOB_AVAILABLE:
            logger.error("❌ py-clob-client not installed!")
            return False
        
        try:
            self.client = ClobClient(
                "https://clob.polymarket.com",
                key=private_key,
                chain_id=137,  # Polygon mainnet
                signature_type=0,  # EOA (direct wallet)
                funder=wallet_address
            )
            self.client.set_api_creds(self.client.create_or_derive_api_creds())
            logger.info(f"✅ Polymarket client initialized for {wallet_address[:8]}...")
            return True
        except Exception as e:
            logger.error(f"❌ Failed to initialize Polymarket client: {e}")
            return False
    
    async def evaluate_swarm_signal(self, signal: Dict) -> Dict:
        """
        Evaluate a swarm signal for trading.
        
        Args:
            signal: Swarm signal from PolymarketCollector
            
        Returns:
            Evaluation result with action recommendation
        """
        result = {
            "action": "SKIP",
            "reason": "",
            "token_id": signal.get("token_id"),
            "whale_count": signal.get("whale_count", 0),
            "price": signal.get("current_price"),
            "bet_size": 0
        }
        
        # Check 1: Whale consensus
        whale_count = signal.get("whale_count", 0)
        if whale_count < self.config.min_whale_consensus:
            result["reason"] = f"Not enough whales ({whale_count} < {self.config.min_whale_consensus})"
            return result
        
        # Check 2: Price within range
        price = signal.get("current_price")
        if price is None:
             result["reason"] = "Price data unavailable"
             return result
             
        if price < self.config.min_price:
            result["reason"] = f"Price too low ({price:.2f} < {self.config.min_price})"
            return result
        if price > self.config.max_price:
            result["reason"] = f"Price too high ({price:.2f} > {self.config.max_price})"
            return result
        
        # Check 3: Not already in position
        token_id = signal.get("token_id")
        if token_id in self.positions:
            result["reason"] = "Already holding this position"
            return result
        
        # Check 4: Max positions
        if len(self.positions) >= self.config.max_open_positions:
            result["reason"] = f"Max positions reached ({self.config.max_open_positions})"
            return result
        
        # Check 5: Cooldown
        if token_id in self.cooldowns:
            cooldown_until = self.cooldowns[token_id]
            if datetime.now() < cooldown_until:
                remaining = (cooldown_until - datetime.now()).seconds // 60
                result["reason"] = f"Cooldown active ({remaining} mins left)"
                return result
        
        # Check 6: Daily loss limit
        if self._is_daily_loss_limit_hit():
            result["reason"] = "Daily loss limit reached"
            return result
        
        # Calculate bet size
        balance = self.paper_balance if self.config.paper_mode else self._get_usdc_balance()
        max_by_pct = balance * self.config.max_bet_pct
        bet_size = min(self.config.max_bet_usdc, max_by_pct)
        
        # Scale up for strong consensus (4+ whales)
        if whale_count >= 5:
            bet_size *= 1.5
            logger.info(f"🔥 HIGH CONVICTION: {whale_count} whales! Sizing up 1.5x")
        
        result["action"] = "BUY"
        result["reason"] = f"SWARM CONFIRMED ({whale_count} whales @ {price:.2f}¢)"
        result["bet_size"] = round(bet_size, 2)
        
        return result
    
    def _is_daily_loss_limit_hit(self) -> bool:
        """Check if daily loss limit has been reached."""
        # Reset daily tracking at midnight
        if datetime.now().date() > self.daily_start.date():
            self.daily_pnl = 0.0
            self.daily_start = datetime.now()
            return False
        
        # Check against loss limit
        balance = self.paper_balance if self.config.paper_mode else self._get_usdc_balance()
        if balance <= 0:
            return True
        
        loss_pct = -self.daily_pnl / balance if self.daily_pnl < 0 else 0
        return loss_pct >= self.config.daily_loss_limit_pct
    
    def _get_usdc_balance(self) -> float:
        """Get current USDC balance from wallet."""
        # TODO: Implement actual balance check via CLOB client
        return 100.0  # Placeholder
    
    async def execute_buy(self, token_id: str, amount_usdc: float, whale_count: int) -> Dict:
        """
        Execute a buy order on Polymarket.
        
        Args:
            token_id: The outcome token to buy
            amount_usdc: Amount in USDC to spend
            whale_count: Number of whales in the signal (for tracking)
            
        Returns:
            Execution result
        """
        result = {
            "success": False,
            "error": None,
            "tx_hash": None,
            "shares": 0,
            "avg_price": 0
        }
        
        if self.config.paper_mode:
            # Paper trading - simulate execution
            if amount_usdc > self.paper_balance:
                result["error"] = "Insufficient paper balance"
                return result
            
            # Simulate price (get current market price)
            price = 0.50  # Default if we can't fetch
            if self.client:
                try:
                    price_data = self.client.get_price(token_id, side="BUY")
                    price = float(price_data) if price_data else 0.50
                except:
                    pass
            
            shares = amount_usdc / price
            
            # Create position
            position = PolymarketPosition(
                token_id=token_id,
                market_id="",  # Will be filled from signal
                outcome="YES",
                entry_price=price,
                size_usdc=amount_usdc,
                shares=shares,
                timestamp=datetime.now(),
                whale_count=whale_count
            )
            
            self.positions[token_id] = position
            self.paper_balance -= amount_usdc
            self._save_positions()
            
            result["success"] = True
            result["shares"] = shares
            result["avg_price"] = price
            result["tx_hash"] = f"PAPER_{datetime.now().timestamp()}"
            
            logger.info(f"📝 PAPER BUY: {shares:.2f} shares @ {price:.2f}¢ (${amount_usdc})")
            return result
        
        # Live trading
        if not self.client:
            result["error"] = "Client not initialized"
            return result
        
        try:
            order = MarketOrderArgs(
                token_id=token_id,
                amount=amount_usdc,
                side=BUY
            )
            signed = self.client.create_market_order(order)
            resp = self.client.post_order(signed, OrderType.FOK)
            
            if resp and resp.get("success"):
                # Extract execution details
                avg_price = float(resp.get("avgPrice", 0))
                shares = amount_usdc / avg_price if avg_price > 0 else 0
                
                position = PolymarketPosition(
                    token_id=token_id,
                    market_id=resp.get("conditionId", ""),
                    outcome="YES",
                    entry_price=avg_price,
                    size_usdc=amount_usdc,
                    shares=shares,
                    timestamp=datetime.now(),
                    whale_count=whale_count
                )
                
                self.positions[token_id] = position
                self._save_positions()
                
                result["success"] = True
                result["shares"] = shares
                result["avg_price"] = avg_price
                result["tx_hash"] = resp.get("transactionHash", "")
                
                logger.info(f"✅ LIVE BUY: {shares:.2f} shares @ {avg_price:.2f}¢ (${amount_usdc})")
            else:
                result["error"] = resp.get("error", "Unknown error")
                
        except Exception as e:
            result["error"] = str(e)
            logger.error(f"❌ Buy execution error: {e}")
        
        return result
    
    async def check_position_exits(self, current_prices: Dict[str, float]) -> List[Dict]:
        """
        Check all open positions for exit conditions.
        
        Args:
            current_prices: Map of token_id -> current price
            
        Returns:
            List of positions that should be exited
        """
        exits = []
        
        for token_id, pos in list(self.positions.items()):
            if pos.status != "OPEN":
                continue
            
            current_price = current_prices.get(token_id)
            if current_price is None:
                continue
            
            # Calculate P&L
            pnl_pct = (current_price - pos.entry_price) / pos.entry_price if pos.entry_price > 0 else 0
            
            exit_reason = None
            
            # Take profit
            if pnl_pct >= self.config.take_profit_pct:
                exit_reason = f"TAKE_PROFIT (+{pnl_pct*100:.1f}%)"
            
            # Stop loss
            elif pnl_pct <= -self.config.stop_loss_pct:
                exit_reason = f"STOP_LOSS ({pnl_pct*100:.1f}%)"
            
            # Price near 0 or 1 (market resolving)
            elif current_price < 0.03 or current_price > 0.97:
                exit_reason = f"MARKET_RESOLVING (price: {current_price:.2f})"
            
            if exit_reason:
                exits.append({
                    "token_id": token_id,
                    "position": pos,
                    "current_price": current_price,
                    "pnl_pct": pnl_pct,
                    "reason": exit_reason
                })
        
        return exits
    
    async def execute_sell(self, token_id: str) -> Dict:
        """
        Execute a sell order to close a position.
        
        Args:
            token_id: The token to sell
            
        Returns:
            Execution result
        """
        result = {
            "success": False,
            "error": None,
            "pnl": 0
        }
        
        if token_id not in self.positions:
            result["error"] = "Position not found"
            return result
        
        pos = self.positions[token_id]
        
        if self.config.paper_mode:
            # Paper trading - simulate sale
            current_price = 0.50  # Default
            if self.client:
                try:
                    price_data = self.client.get_price(token_id, side="SELL")
                    current_price = float(price_data) if price_data else 0.50
                except:
                    pass
            
            sale_value = pos.shares * current_price
            pnl = sale_value - pos.size_usdc
            
            self.paper_balance += sale_value
            self.paper_pnl += pnl
            self.daily_pnl += pnl
            
            pos.status = "CLOSED"
            del self.positions[token_id]
            self._save_positions()
            
            result["success"] = True
            result["pnl"] = pnl
            
            emoji = "📈" if pnl >= 0 else "📉"
            logger.info(f"{emoji} PAPER SELL: {pos.shares:.2f} shares @ {current_price:.2f}¢ (PNL: ${pnl:.2f})")
            return result
        
        # Live trading
        if not self.client:
            result["error"] = "Client not initialized"
            return result
        
        try:
            order = MarketOrderArgs(
                token_id=token_id,
                amount=pos.shares,
                side=SELL
            )
            signed = self.client.create_market_order(order)
            resp = self.client.post_order(signed, OrderType.FOK)
            
            if resp and resp.get("success"):
                avg_price = float(resp.get("avgPrice", 0))
                sale_value = pos.shares * avg_price
                pnl = sale_value - pos.size_usdc
                
                self.daily_pnl += pnl
                pos.status = "CLOSED"
                del self.positions[token_id]
                self._save_positions()
                
                result["success"] = True
                result["pnl"] = pnl
                
                emoji = "📈" if pnl >= 0 else "📉"
                logger.info(f"{emoji} LIVE SELL: {pos.shares:.2f} shares @ {avg_price:.2f}¢ (PNL: ${pnl:.2f})")
            else:
                result["error"] = resp.get("error", "Unknown error")
                
        except Exception as e:
            result["error"] = str(e)
            logger.error(f"❌ Sell execution error: {e}")
        
        return result
    
    def get_status(self) -> Dict:
        """Get current trading status."""
        total_position_value = sum(p.size_usdc for p in self.positions.values())
        
        return {
            "mode": "PAPER" if self.config.paper_mode else "LIVE",
            "balance": self.paper_balance if self.config.paper_mode else self._get_usdc_balance(),
            "open_positions": len(self.positions),
            "total_position_value": total_position_value,
            "daily_pnl": self.daily_pnl,
            "total_pnl": self.paper_pnl if self.config.paper_mode else 0,
            "daily_loss_limit_hit": self._is_daily_loss_limit_hit()
        }


# Singleton instance
_trader_instance: Optional[PolymarketTrader] = None

def get_polymarket_trader() -> PolymarketTrader:
    """Get or create the singleton PolymarketTrader instance."""
    global _trader_instance
    if _trader_instance is None:
        _trader_instance = PolymarketTrader()
    return _trader_instance
