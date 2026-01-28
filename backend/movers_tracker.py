"""
Movers Tracker - Collects and persists pump.fun mover data for research.
Phase 69: Recreated to fix broken data collection.

This tracker runs in the background and periodically:
1. Fetches top movers from pump.fun
2. Saves snapshots to the MoverSnapshot table
3. Enables historical analysis of token momentum patterns
"""
import asyncio
import logging
import requests
import time
import os
import re
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# Singleton instance
_tracker_instance = None

class MoversTracker:
    """
    Tracks mover data from pump.fun and saves to database.
    """
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.proxy_url = os.getenv('RESIDENTIAL_PROXY', '').strip()
        
        # Track intervals
        self._last_snapshot = 0
        self._snapshot_interval = 300  # 5 minutes between snapshots
        
        # Cache for API endpoint that works
        self._working_endpoint = None
        
        # Background task reference
        self._bg_task = None
        self._running = False
    
    def _get_session(self):
        """Get a requests session with optional proxy."""
        session = requests.Session()
        if self.proxy_url:
            session.proxies = {
                'http': self.proxy_url,
                'https': self.proxy_url
            }
        return session
    
    async def fetch_movers(self, limit=30):
        """
        Fetch top movers from pump.fun.
        Returns list of dicts with mover data.
        """
        endpoints = [
            "https://frontend-api-v3.pump.fun/coins/top-runners",
            "https://frontend-api.pump.fun/coins/top-runners",
            "https://frontend-api.pump.fun/coins/trending"
        ]
        
        # Try cached endpoint first
        if self._working_endpoint:
            endpoints.insert(0, self._working_endpoint)
        
        session = self._get_session()
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'application/json'
        }
        
        for endpoint in endpoints:
            try:
                # Run in executor to avoid blocking
                loop = asyncio.get_event_loop()
                resp = await loop.run_in_executor(
                    None,
                    lambda: session.get(endpoint, timeout=15, headers=headers)
                )
                
                if resp.status_code == 200:
                    data = resp.json()
                    
                    # Handle different response formats
                    if isinstance(data, list):
                        tokens = data[:limit]
                    elif isinstance(data, dict):
                        tokens = data.get('coins', data.get('data', []))[:limit]
                    else:
                        tokens = []
                    
                    if tokens:
                        self._working_endpoint = endpoint
                        self.logger.info(f"📊 Fetched {len(tokens)} movers from {endpoint}")
                        return tokens
                        
            except Exception as e:
                self.logger.debug(f"Endpoint {endpoint} failed: {e}")
                continue
        
        self.logger.warning("⚠️ Could not fetch movers from any endpoint")
        return []
    
    async def save_snapshot(self, tokens):
        """
        Save mover data to database as snapshots.
        """
        if not tokens:
            return 0
        
        try:
            from database import SessionLocal
            from models import MoverSnapshot
            
            db = SessionLocal()
            saved = 0
            
            try:
                for item in tokens:
                    # Handle nested 'coin' object from pump.fun API
                    token = item.get('coin', item) if isinstance(item, dict) else item
                    
                    # Extract relevant fields
                    mint = token.get('mint', token.get('token_address', ''))
                    symbol = token.get('symbol', token.get('ticker', ''))
                    name = token.get('name', '')
                    
                    # Market cap - try different field names
                    mc = token.get('usd_market_cap', 
                         token.get('marketCap',
                         token.get('market_cap', 0))) or 0
                    
                    # Volume and buyers - use reply_count as activity proxy
                    sol_volume = token.get('total_volume', 
                                 token.get('volume',
                                 token.get('sol_volume', 0))) or 0
                    
                    unique_buyers = token.get('unique_wallet_count',
                                    token.get('unique_buyers',
                                    token.get('reply_count', 0))) or 0
                    
                    buy_count = token.get('buy_count', 
                               token.get('txns',
                               token.get('reply_count', 0))) or 0
                    
                    # Calculate momentum score
                    score = self._calculate_score(mc, unique_buyers, sol_volume)
                    
                    if mint:  # Only save if we have a mint address
                        snapshot = MoverSnapshot(
                            mint=mint,
                            symbol=symbol or name[:10] if name else None,
                            mc_usd=mc,
                            unique_buyers=unique_buyers,
                            buy_count=buy_count,
                            sol_volume=sol_volume,
                            score=score,
                            snapshot_at=datetime.utcnow()
                        )
                        db.add(snapshot)
                        saved += 1
                
                db.commit()
                self.logger.info(f"✅ Saved {saved} mover snapshots to database")
                return saved
                
            except Exception as e:
                db.rollback()
                self.logger.error(f"❌ Database error saving snapshots: {e}")
                return 0
            finally:
                db.close()
                
        except ImportError as e:
            self.logger.error(f"❌ Import error: {e}")
            return 0
    
    def _calculate_score(self, mc, buyers, volume):
        """
        Calculate momentum score based on key metrics.
        Higher is better. Score range: 0-100
        """
        score = 0
        
        # Market cap scoring (lower MC = higher potential)
        if mc and mc > 0:
            if mc < 10000:
                score += 30  # Very early
            elif mc < 50000:
                score += 25  # Early
            elif mc < 100000:
                score += 20  # Good entry
            elif mc < 500000:
                score += 15  # Moderate risk
            else:
                score += 5   # Higher MC
        
        # Buyer scoring (more unique buyers = more interest)
        if buyers:
            if buyers >= 50:
                score += 30
            elif buyers >= 20:
                score += 25
            elif buyers >= 10:
                score += 20
            elif buyers >= 5:
                score += 15
            else:
                score += 5
        
        # Volume scoring (higher volume = more activity)
        if volume:
            if volume >= 10:
                score += 30
            elif volume >= 5:
                score += 25
            elif volume >= 2:
                score += 20
            elif volume >= 1:
                score += 15
            else:
                score += 10
        
        return min(score, 100)  # Cap at 100
    
    async def run_snapshot_cycle(self):
        """
        Run a single snapshot cycle: fetch and save.
        """
        now = time.time()
        
        # Check interval
        if (now - self._last_snapshot) < self._snapshot_interval:
            remaining = self._snapshot_interval - (now - self._last_snapshot)
            self.logger.debug(f"⏳ Next snapshot in {remaining:.0f}s")
            return 0
        
        self._last_snapshot = now
        
        # Fetch and save
        tokens = await self.fetch_movers(limit=30)
        saved = await self.save_snapshot(tokens)
        
        return saved
    
    async def start_background_tracking(self):
        """
        Start the background tracking loop.
        Runs every 5 minutes to collect mover data.
        """
        if self._running:
            self.logger.info("📊 Movers tracker already running")
            return
        
        self._running = True
        self.logger.info("🚀 Starting movers tracker background task")
        
        while self._running:
            try:
                await self.run_snapshot_cycle()
            except Exception as e:
                self.logger.error(f"❌ Snapshot cycle error: {e}")
            
            # Wait before next cycle
            await asyncio.sleep(60)  # Check every minute
    
    def stop(self):
        """Stop the background tracking."""
        self._running = False
        self.logger.info("🛑 Movers tracker stopped")
    
    async def get_movers(self, limit=15, min_buyers=2, min_sol_volume=0.3):
        """
        Get current movers (for API endpoint).
        Returns filtered list based on criteria.
        """
        tokens = await self.fetch_movers(limit=50)
        
        # Filter based on criteria
        filtered = []
        for token in tokens:
            buyers = token.get('unique_wallet_count', token.get('unique_buyers', 0)) or 0
            volume = token.get('total_volume', token.get('sol_volume', 0)) or 0
            
            if buyers >= min_buyers and volume >= min_sol_volume:
                filtered.append(token)
        
        return filtered[:limit]
    
    async def get_stats(self):
        """Get tracking stats."""
        try:
            from database import SessionLocal
            from models import MoverSnapshot
            from sqlalchemy import func
            
            db = SessionLocal()
            try:
                total = db.query(MoverSnapshot).count()
                
                # Last 24h count
                yesterday = datetime.utcnow() - timedelta(days=1)
                recent = db.query(MoverSnapshot).filter(
                    MoverSnapshot.snapshot_at > yesterday
                ).count()
                
                # Last snapshot time
                last = db.query(MoverSnapshot).order_by(
                    MoverSnapshot.snapshot_at.desc()
                ).first()
                
                return {
                    "total_snapshots": total,
                    "last_24h": recent,
                    "last_snapshot": last.snapshot_at.isoformat() if last else None,
                    "tracking_active": self._running
                }
            finally:
                db.close()
                
        except Exception as e:
            self.logger.error(f"Stats error: {e}")
            return {"error": str(e)}


def get_movers_tracker():
    """Get or create the singleton tracker instance."""
    global _tracker_instance
    if _tracker_instance is None:
        _tracker_instance = MoversTracker()
    return _tracker_instance


async def start_movers_tracking():
    """Start the movers tracking background task."""
    tracker = get_movers_tracker()
    await tracker.start_background_tracking()


# Test script
if __name__ == "__main__":
    import asyncio
    import sys
    sys.stdout.reconfigure(encoding='utf-8')
    logging.basicConfig(level=logging.INFO)
    
    async def test():
        tracker = MoversTracker()
        
        print("[SEARCH] Fetching movers...")
        tokens = await tracker.fetch_movers(limit=10)
        
        print(f"\n[CHART] Found {len(tokens)} tokens:")
        for item in tokens[:5]:
            # Handle nested 'coin' object
            t = item.get('coin', item) if isinstance(item, dict) else item
            name = t.get('symbol', t.get('name', 'Unknown'))
            mc = t.get('usd_market_cap', 0)
            print(f"  - {name}: MC ${mc:,.0f}")
        
        print("\n[SAVE] Saving snapshot...")
        saved = await tracker.save_snapshot(tokens)
        print(f"[OK] Saved {saved} snapshots")
    
    asyncio.run(test())
