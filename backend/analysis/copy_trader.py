import asyncio
import logging
import json
import os
import random
from datetime import datetime
from collections import defaultdict
from collectors.dex_scout import DexScout
from collectors.wallet_collector import WalletCollector

class SmartCopyTrader:
    """
    The Orchestrator.
    1. Finds Trending Tokens (DexScout)
    2. Identifies Active Traders (Helius)
    3. Filters for 'Human' Traders (WalletCollector)
    4. Listens for 'Swarm' Signals (3+ Humans Buying)
    """
    def __init__(self):
        self.dex_scout = DexScout()
        self.collector = WalletCollector()
        self.logger = logging.getLogger(__name__)
        self.collector = WalletCollector()
        self.logger = logging.getLogger(__name__)
        # DB Persistence
        self.qualified_wallets = self._load_wallets()
        self.active_swarms = {} # token_mint -> set(wallet_addresses)

    def _load_wallets(self):
        """Load wallets from Database."""
        try:
            from database import SessionLocal
            from models import WhaleWallet
            
            db = SessionLocal()
            wallets_db = db.query(WhaleWallet).all()
            
            # Convert to internal dict format
            # Format: {address: {stats: ..., discovered_on: ...}}
            result = {}
            for w in wallets_db:
                result[w.address] = {
                    "stats": w.stats,
                    "discovered_on": w.discovered_on,
                    "discovered_at": w.discovered_at.isoformat() if w.discovered_at else None,
                    "score": w.score
                }
            
            db.close()
            return result
        except Exception as e:
            self.logger.error(f"Error loading wallets from DB: {e}")
            return {}
    
    def _save_wallet_to_db(self, address, data):
        """Save a single wallet to DB."""
        try:
            from database import SessionLocal
            from models import WhaleWallet
            
            db = SessionLocal()
            
            # Check if exists
            existing = db.query(WhaleWallet).filter(WhaleWallet.address == address).first()
            if not existing:
                new_wallet = WhaleWallet(
                    address=address,
                    stats=data['stats'],
                    discovered_on=data['discovered_on'],
                    score=data['score']
                )
                db.add(new_wallet)
            else:
                existing.stats = data['stats'] # Update stats
            
            db.commit()
            db.close()
        except Exception as e:
            self.logger.error(f"Error saving wallet to DB: {e}")

    def _prune_old_whales(self, keep_count=100):
        """Remove oldest whales to keep list fresh."""
        try:
            from database import SessionLocal
            from models import WhaleWallet
            
            # Sort by discovery date (descending)
            sorted_wallets = sorted(
                self.qualified_wallets.items(), 
                key=lambda x: x[1].get('discovered_at', ''),
                reverse=True
            )
            
            # Keep top N
            to_keep = dict(sorted_wallets[:keep_count])
            to_remove = dict(sorted_wallets[keep_count:])
            
            self.qualified_wallets = to_keep
            
            # Remove from DB
            if to_remove:
                db = SessionLocal()
                for addr in to_remove.keys():
                    db.query(WhaleWallet).filter(WhaleWallet.address == addr).delete()
                db.commit()
                db.close()
                self.logger.info(f"🧹 Pruned {len(to_remove)} old whales from DB.")
                
        except Exception as e:
            self.logger.error(f"Error pruning whales: {e}")

    async def scan_market_for_whales(self, max_pairs=10, max_traders_per_pair=5):
        """
        Main Routine: Scan trending tokens to find new qualified wallets.
        """
        self.logger.info("🌊 Starting Whale Hunt...")
        
        # 1. Get Trending Pairs
        pairs = await self.dex_scout.get_trending_solana_pairs(limit=max_pairs)
        self.logger.info(f"🔎 Found {len(pairs)} trending pairs to scan.")
        
        new_wallets = 0
        
        for pair in pairs:
            token_address = pair.get('baseToken', {}).get('address')
            symbol = pair.get('baseToken', {}).get('symbol')
            if not token_address: continue
            
            self.logger.info(f"  👉 Scanning {symbol} ({token_address})...")
            
            # 2. Get Recent Signatures (Trades)
            sigs = self.collector.get_signatures_for_address(token_address, limit=50) # Look at last 50 trades
            if not sigs: continue
            
            sig_list = [s['signature'] for s in sigs]
            
            # 3. Parse Transactions to find Signers
            parsed_txs = self.collector.batch_fetch_parsed_txs(sig_list)
            
            # Extract unique signers (feePayer or from token transfers)
            # Simplification: Use feePayer (usually the trader)
            traders = set()
            for tx in parsed_txs:
                if tx.get('type') == 'SWAP':
                    # Helius parsed transaction
                    # Try to find the account that paid fees or signed
                    # feePayer is top level usually
                    payer = tx.get('feePayer')
                    if payer:
                        traders.add(payer)
            
            self.logger.info(f"    found {len(traders)} unique traders.")
            
            # 4. Analyze Each Trader
            checked_count = 0
            for wallet in traders:
                if checked_count >= max_traders_per_pair: break
                if wallet in self.qualified_wallets:
                    continue # Already known
                
                # Analyze (Expensive! Rate limit applies)
                # We randomize or limit to avoid spamming Helius in loop
                stats = self.collector.analyze_wallet(wallet, lookback_txs=50)
                checked_count += 1
                
                if stats and stats.get('is_qualified'):
                    self.logger.info(f"    🔥 FOUND QUALIFIED TRADER: {wallet} (P10: {stats['p10_holding_time_sec']}s)")
                    wallet_data = {
                        "discovered_on": symbol,
                        "discovered_at": datetime.now().isoformat(),
                        "stats": stats,
                        "score": 10 # Base Score
                    }
                    self.qualified_wallets[wallet] = wallet_data
                    new_wallets += 1
                    self._save_wallet_to_db(wallet, wallet_data)
                    
        # Pruning: Keep only top 100 whales (by score/freshness)
        if len(self.qualified_wallets) > 100:
            self._prune_old_whales()
            
            # Respect rate limits
            await asyncio.sleep(1) 
            
        self.logger.info(f"✅ Hunt Complete. Found {new_wallets} new qualified wallets. Total: {len(self.qualified_wallets)}")
        return new_wallets

    async def monitor_swarm(self, window_minutes=15, min_buyers=3):
        """
        Real-time Swarm Detector.
        Polls all Qualified Wallets.
        Returns list of (token_mint, token_symbol) to BUY.
        """
        if not self.qualified_wallets:
            return []
            
        signals = []
        cluster = defaultdict(set) # token_mint -> {wallet_addresses}
        
        # 1. Check each wallet for recent activity (use async to not block)
        for wallet in list(self.qualified_wallets.keys()):  # Copy keys to avoid mutation error
            # Fetch last 10 txs (ASYNC to not block Discord heartbeat)
            txs = await self.collector.fetch_helius_history_async(wallet, limit=10)
            if not txs: continue
            
            now = datetime.utcnow()
            
            for tx in txs:
                ts = tx.get('timestamp', 0)
                if not ts: continue
                
                # Check Time Window
                tx_time = datetime.utcfromtimestamp(ts)
                age_min = (now - tx_time).total_seconds() / 60
                
                if age_min > window_minutes:
                    continue # Too old
                
                # Check if it was a BUY (Swap In)
                # Parse direction
                transfers = tx.get('tokenTransfers', [])
                tokens_in = [t.get('mint') for t in transfers if t.get('toUserAccount') == wallet]
                
                # Filter out SOL/USDC imports
                SOL_MINT = "So11111111111111111111111111111111111111112"
                USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
                STABLE_MINTS = {SOL_MINT, USDC_MINT, "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"}

                for mint in tokens_in:
                    if mint not in STABLE_MINTS:
                        cluster[mint].add(wallet)
        
        # 2. Check Thresholds
        for mint, buyers in cluster.items():
            if len(buyers) >= min_buyers:
                self.logger.info(f"🚨 SWARM DETECTED: {len(buyers)} Qualified Wallets bought {mint}!")
                signals.append(mint)
                # Track participants for Exit Logic
                if mint not in self.active_swarms:
                    self.active_swarms[mint] = set()
                self.active_swarms[mint].update(buyers)
                
        return signals

    async def check_swarm_exit(self, token_mint):
        """
        Checks if the swarm has dumped the token.
        Returns: True (Dump Detected) | False (Hold)
        """
        participants = self.active_swarms.get(token_mint, set())
        if not participants: return False
        
        sold_count = 0
        total = len(participants)
        if total == 0: return False
        
        # Check if > 50% have sold
        for wallet in participants:
            # Check recent history for SELL of this token (Last 10 txs)
            txs = self.collector.fetch_helius_history(wallet, limit=10)
            if not txs: continue
            
            did_sell = False
            for tx in txs:
                # Check for SELL: Token Input -> Stable/SOL Output
                transfers = tx.get('tokenTransfers', [])
                
                # Did this wallet SEND the token?
                sent_token = False
                for t in transfers:
                    if t.get('fromUserAccount') == wallet and t.get('mint') == token_mint:
                        sent_token = True
                        break
                
                if sent_token:
                    did_sell = True
                    break
            
            if did_sell:
                sold_count += 1
                
        dump_ratio = sold_count / total
        if dump_ratio >= 0.5:
            self.logger.warning(f"📉 SWARM DUMP DETECTED for {token_mint}: {sold_count}/{total} sold.")
            return True
            
        return False
