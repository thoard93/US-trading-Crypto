"""
Polymarket Data Collector
Fetches leaderboard, markets, and whale activity from Polymarket APIs.
"""
import aiohttp
import asyncio
import logging
from typing import List, Dict, Optional
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger(__name__)

# API Endpoints
DATA_API = "https://data-api.polymarket.com"
CLOB_API = "https://clob.polymarket.com"
GAMMA_API = "https://gamma-api.polymarket.com"


@dataclass
class TopTrader:
    """Represents a top trader from the leaderboard."""
    rank: int
    wallet: str  # proxyWallet address
    username: str
    pnl: float  # Profit/Loss in USD
    volume: float
    predictions: int


@dataclass
class WhalePosition:
    """Represents a position held by a whale."""
    wallet: str
    market_id: str
    token_id: str
    outcome: str  # YES or NO
    size: float
    avg_price: float
    current_price: float
    timestamp: datetime


class PolymarketCollector:
    """
    Collects data from Polymarket APIs for copy-trading.
    
    Safety Features:
    - Rate limiting to avoid API bans
    - Caching to reduce API calls
    - Error handling with graceful fallbacks
    """
    
    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None
        self.leaderboard_cache: List[TopTrader] = []
        self.whale_positions_cache: Dict[str, List[WhalePosition]] = {}
        self.last_leaderboard_fetch: Optional[datetime] = None
        self.cache_ttl_seconds = 300  # 5 minutes
        
    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session."""
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session
    
    async def close(self):
        """Close the aiohttp session."""
        if self.session and not self.session.closed:
            await self.session.close()
    
    async def fetch_leaderboard(
        self,
        category: str = "OVERALL",
        time_period: str = "WEEK",
        order_by: str = "PNL",
        limit: int = 25
    ) -> List[TopTrader]:
        """
        Fetch top traders from Polymarket leaderboard.
        
        Args:
            category: OVERALL, POLITICS, SPORTS, CRYPTO
            time_period: DAY, WEEK, MONTH, ALL
            order_by: PNL or VOL
            limit: Number of traders (1-50)
            
        Returns:
            List of TopTrader objects
        """
        # Check cache
        if (
            self.leaderboard_cache 
            and self.last_leaderboard_fetch 
            and (datetime.now() - self.last_leaderboard_fetch).seconds < self.cache_ttl_seconds
        ):
            logger.debug("Using cached leaderboard data")
            return self.leaderboard_cache
        
        url = f"{DATA_API}/v1/leaderboard"
        params = {
            "category": category,
            "timePeriod": time_period,
            "orderBy": order_by,
            "limit": limit
        }
        
        try:
            session = await self._get_session()
            async with session.get(url, params=params) as resp:
                if resp.status != 200:
                    logger.error(f"Leaderboard API error: {resp.status}")
                    return self.leaderboard_cache  # Return cached data on error
                
                data = await resp.json()
                traders = []
                
                for item in data:
                    trader = TopTrader(
                        rank=item.get("rank", 0),
                        wallet=item.get("proxyWallet", ""),
                        username=item.get("userName", "Unknown"),
                        pnl=float(item.get("pnl", 0)),
                        volume=float(item.get("vol", 0)),
                        predictions=int(item.get("predictions", 0))
                    )
                    traders.append(trader)
                
                self.leaderboard_cache = traders
                self.last_leaderboard_fetch = datetime.now()
                logger.info(f"✅ Fetched {len(traders)} top traders from Polymarket leaderboard")
                return traders
                
        except Exception as e:
            logger.error(f"❌ Error fetching leaderboard: {e}")
            return self.leaderboard_cache
    
    async def fetch_whale_positions(self, wallet: str) -> List[WhalePosition]:
        """
        Fetch current positions for a specific wallet.
        
        Args:
            wallet: The proxyWallet address of the trader
            
        Returns:
            List of WhalePosition objects
        """
        url = f"{DATA_API}/v1/positions"
        params = {"user": wallet}
        
        try:
            session = await self._get_session()
            async with session.get(url, params=params) as resp:
                if resp.status != 200:
                    logger.warning(f"Positions API error for {wallet[:8]}...: {resp.status}")
                    return self.whale_positions_cache.get(wallet, [])
                
                data = await resp.json()
                positions = []
                
                for item in data:
                    pos = WhalePosition(
                        wallet=wallet,
                        market_id=item.get("conditionId", ""),
                        token_id=item.get("tokenId", ""),
                        outcome=item.get("outcome", ""),
                        size=float(item.get("size", 0)),
                        avg_price=float(item.get("avgPrice", 0)),
                        current_price=float(item.get("curPrice", 0)),
                        timestamp=datetime.now()
                    )
                    positions.append(pos)
                
                self.whale_positions_cache[wallet] = positions
                return positions
                
        except Exception as e:
            logger.error(f"❌ Error fetching positions for {wallet[:8]}...: {e}")
            return self.whale_positions_cache.get(wallet, [])
    
    async def fetch_markets(self, limit: int = 50, active_only: bool = True) -> List[Dict]:
        """
        Fetch available markets from Polymarket.
        
        Args:
            limit: Maximum number of markets to return
            active_only: Only return active (not resolved) markets
            
        Returns:
            List of market dictionaries
        """
        # Use CLOB API for simplified markets
        url = f"{CLOB_API}/simplified-markets"
        params = {"limit": limit}
        
        try:
            session = await self._get_session()
            async with session.get(url, params=params) as resp:
                if resp.status != 200:
                    logger.error(f"Markets API error: {resp.status}")
                    return []
                
                data = await resp.json()
                markets = data.get("data", [])
                
                if active_only:
                    markets = [m for m in markets if not m.get("closed", False)]
                
                logger.info(f"📊 Fetched {len(markets)} active markets from Polymarket")
                return markets
                
        except Exception as e:
            logger.error(f"❌ Error fetching markets: {e}")
            return []
    
    async def get_market_price(self, token_id: str, side: str = "BUY") -> Optional[float]:
        """
        Get current price for a specific market token.
        
        Args:
            token_id: The token ID for the outcome
            side: BUY or SELL
            
        Returns:
            Price as float (0-1) or None if unavailable
        """
        url = f"{CLOB_API}/price"
        params = {"token_id": token_id, "side": side}
        
        try:
            session = await self._get_session()
            async with session.get(url, params=params) as resp:
                if resp.status != 200:
                    return None
                
                data = await resp.json()
                return float(data.get("price", 0))
                
        except Exception as e:
            logger.error(f"❌ Error fetching price: {e}")
            return None
    
    async def detect_whale_swarm(
        self,
        min_whales: int = 3,
        time_window_minutes: int = 60
    ) -> List[Dict]:
        """
        Detect when multiple whales are betting on the same market (SWARM SIGNAL).
        
        This is the key copy-trading signal - if multiple top traders
        are betting the same direction, it's a strong signal.
        
        Args:
            min_whales: Minimum number of whales needed for a signal
            time_window_minutes: Look for bets within this time window
            
        Returns:
            List of swarm signals with market info and whale count
        """
        # First, get top traders
        traders = await self.fetch_leaderboard(limit=15)
        
        if not traders:
            logger.warning("No traders found for swarm detection")
            return []
        
        # Collect all whale positions
        market_bets: Dict[str, Dict] = {}  # token_id -> {wallets: [], outcome: str, ...}
        
        for trader in traders:
            positions = await self.fetch_whale_positions(trader.wallet)
            
            for pos in positions:
                if pos.token_id not in market_bets:
                    market_bets[pos.token_id] = {
                        "token_id": pos.token_id,
                        "market_id": pos.market_id,
                        "outcome": pos.outcome,
                        "wallets": [],
                        "total_size": 0,
                        "avg_price": 0
                    }
                
                market_bets[pos.token_id]["wallets"].append(trader.wallet)
                market_bets[pos.token_id]["total_size"] += pos.size
            
            # Small delay to avoid rate limiting
            await asyncio.sleep(0.2)
        
        # Filter for swarm signals
        swarm_signals = []
        for token_id, data in market_bets.items():
            if len(data["wallets"]) >= min_whales:
                # Get current price
                price = await self.get_market_price(token_id)
                
                signal = {
                    "token_id": token_id,
                    "market_id": data["market_id"],
                    "outcome": data["outcome"],
                    "whale_count": len(data["wallets"]),
                    "total_whale_size": data["total_size"],
                    "current_price": price,
                    "wallets": data["wallets"]
                }
                swarm_signals.append(signal)
                logger.info(f"🐋 SWARM SIGNAL: {len(data['wallets'])} whales on {token_id[:8]}...")
        
        return swarm_signals


# Singleton instance
_collector_instance: Optional[PolymarketCollector] = None

def get_polymarket_collector() -> PolymarketCollector:
    """Get or create the singleton PolymarketCollector instance."""
    global _collector_instance
    if _collector_instance is None:
        _collector_instance = PolymarketCollector()
    return _collector_instance
