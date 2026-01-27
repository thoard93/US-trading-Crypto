"""
Movers Tracker - Phase 57 Bot Farm Hardening
Tracks pump.fun token momentum using Helius webhook data.
Identifies low MC tokens with sudden buying activity.
"""
import os
import time
import logging
from collections import defaultdict
from datetime import datetime, timedelta

logger = logging.getLogger("MoversTracker")

class MoversTracker:
    """
    Tracks token momentum from Helius webhook data.
    Identifies "movers" = tokens with sudden increased buy activity.
    """
    
    def __init__(self, min_mc_usd=3000, max_mc_usd=100000):
        # Token activity: {mint: [{'timestamp': ts, 'sol_amount': x, 'buyer': addr}, ...]}
        self.activity = defaultdict(list)
        
        # Token metadata cache: {mint: {'symbol': ..., 'mc': ..., 'last_updated': ts}}
        self.token_cache = {}
        
        # Filters
        self.min_mc = min_mc_usd
        self.max_mc = max_mc_usd
        
        # Activity window
        self.window_minutes = 15
        
        # DexScreener for MC lookup
        self.dex_scout = None
        try:
            from collectors.dex_scout import DexScout
            self.dex_scout = DexScout()
        except:
            logger.warning("DexScout not available for MC lookups")
    
    def process_transactions(self, transactions):
        """
        Process Helius Enhanced Transactions to track token activity.
        Called by webhook_listener after receiving data.
        """
        now = time.time()
        new_activity = 0
        
        for tx in transactions:
            # Get transaction details
            buyer = tx.get('feePayer')
            tx_type = tx.get('type', '')
            
            # Only track SWAP transactions (buys)
            if 'SWAP' not in tx_type:
                continue
            
            # Extract token transfers
            token_transfers = tx.get('tokenTransfers', [])
            
            for transfer in token_transfers:
                mint = transfer.get('mint')
                if not mint:
                    continue
                
                # Skip SOL/USDC/USDT transfers
                if mint in ['So11111111111111111111111111111111111111112', 
                            'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v']:  # SOL, USDC
                    continue
                
                # Get transfer amount (in tokens)
                token_amount = float(transfer.get('tokenAmount', 0))
                
                # Estimate SOL amount from native transfers
                sol_amount = 0
                for native in tx.get('nativeTransfers', []):
                    if native.get('fromUserAccount') == buyer:
                        sol_amount += native.get('amount', 0) / 1e9  # lamports to SOL
                
                if token_amount > 0 and sol_amount > 0:
                    self.activity[mint].append({
                        'timestamp': now,
                        'sol_amount': sol_amount,
                        'buyer': buyer,
                        'token_amount': token_amount
                    })
                    new_activity += 1
        
        # Prune old activity
        self._prune_old_activity()
        
        return new_activity
    
    def _prune_old_activity(self):
        """Remove activity older than window."""
        cutoff = time.time() - (self.window_minutes * 60)
        
        for mint in list(self.activity.keys()):
            self.activity[mint] = [
                a for a in self.activity[mint] 
                if a['timestamp'] > cutoff
            ]
            # Remove empty entries
            if not self.activity[mint]:
                del self.activity[mint]
    
    async def get_movers(self, limit=10, min_buyers=2, min_sol_volume=0.5):
        """
        Get top movers - tokens with sudden buying activity.
        
        Args:
            limit: Max number of movers to return
            min_buyers: Minimum unique buyers required
            min_sol_volume: Minimum total SOL volume required
            
        Returns:
            List of dicts with mover info
        """
        self._prune_old_activity()
        
        movers = []
        
        for mint, activities in self.activity.items():
            # Calculate metrics
            unique_buyers = len(set(a['buyer'] for a in activities))
            total_sol = sum(a['sol_amount'] for a in activities)
            buy_count = len(activities)
            
            # Apply filters
            if unique_buyers < min_buyers:
                continue
            if total_sol < min_sol_volume:
                continue
            
            # Get token info (cached)
            token_info = await self._get_token_info(mint)
            mc = token_info.get('mc', 0)
            symbol = token_info.get('symbol', mint[:8])
            
            # MC filter
            if mc > 0 and (mc < self.min_mc or mc > self.max_mc):
                continue
            
            # Calculate momentum score
            # Score = buyers * sqrt(volume) * recency_factor
            recency_factor = 1.0
            if activities:
                avg_age = (time.time() - sum(a['timestamp'] for a in activities) / len(activities)) / 60
                recency_factor = max(0.1, 1 - (avg_age / self.window_minutes))
            
            score = unique_buyers * (total_sol ** 0.5) * recency_factor
            
            movers.append({
                'mint': mint,
                'symbol': symbol,
                'mc': mc,
                'buyers': unique_buyers,
                'buys': buy_count,
                'sol_volume': round(total_sol, 3),
                'score': round(score, 2),
                'last_buy_ago_s': int(time.time() - max(a['timestamp'] for a in activities))
            })
        
        # Sort by score
        movers.sort(key=lambda x: x['score'], reverse=True)
        
        return movers[:limit]
    
    async def _get_token_info(self, mint):
        """Get token symbol and MC from cache or DexScreener."""
        if mint in self.token_cache:
            cached = self.token_cache[mint]
            # Cache valid for 5 minutes
            if time.time() - cached.get('last_updated', 0) < 300:
                return cached
        
        # Fetch from DexScreener
        info = {'symbol': mint[:8], 'mc': 0, 'last_updated': time.time()}
        
        if self.dex_scout:
            try:
                pair = await self.dex_scout.get_pair_info(mint)
                if pair:
                    info['symbol'] = pair.get('baseToken', {}).get('symbol', mint[:8])
                    info['mc'] = pair.get('marketCap', 0) or pair.get('fdv', 0)
            except Exception as e:
                logger.debug(f"DexScout lookup failed for {mint[:16]}: {e}")
        
        self.token_cache[mint] = info
        return info
    
    def get_activity_summary(self):
        """Get summary stats for logging/monitoring."""
        self._prune_old_activity()
        
        total_tokens = len(self.activity)
        total_buys = sum(len(acts) for acts in self.activity.values())
        total_sol = sum(sum(a['sol_amount'] for a in acts) for acts in self.activity.values())
        
        return {
            'tokens_tracked': total_tokens,
            'buys_in_window': total_buys,
            'sol_volume': round(total_sol, 2),
            'window_minutes': self.window_minutes
        }
    
    def reset(self):
        """Clear all activity data."""
        self.activity.clear()
        self.token_cache.clear()
    
    async def log_snapshot(self):
        """
        Log current top movers to database for research.
        Call this periodically (e.g., every 10 minutes) to track MC changes over time.
        """
        try:
            from database import SessionLocal
            import models
            
            db = SessionLocal()
            movers = await self.get_movers(limit=20, min_buyers=2, min_sol_volume=0.2)
            
            logged = 0
            for m in movers:
                snapshot = models.MoverSnapshot(
                    mint=m['mint'],
                    symbol=m['symbol'],
                    mc_usd=m.get('mc', 0),
                    unique_buyers=m['buyers'],
                    buy_count=m['buys'],
                    sol_volume=m['sol_volume'],
                    score=m['score']
                )
                db.add(snapshot)
                logged += 1
            
            db.commit()
            db.close()
            logger.info(f"📊 Logged {logged} mover snapshots for research")
            return logged
        except Exception as e:
            logger.error(f"Failed to log mover snapshots: {e}")
            return 0


# Singleton for use across modules
_tracker_instance = None

def get_movers_tracker():
    global _tracker_instance
    if _tracker_instance is None:
        _tracker_instance = MoversTracker()
    return _tracker_instance
