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
        # DB Persistence
        self.qualified_wallets = self._load_wallets()
        self.active_swarms = self._load_swarms() # Restore active swarms
        self._last_signatures = {} # Cache for {wallet: signature}
        self._recent_whale_activity = [] # List of {wallet, mint, timestamp, signature}
        self._processed_signatures = set() # O(1) duplicate checking
        self._scan_index = 0

    def _load_swarms(self):
        """Restore active swarm participants from DB."""
        try:
            from database import SessionLocal
            from models import ActiveSwarm
            
            db = SessionLocal()
            swarms_db = db.query(ActiveSwarm).all()
            
            result = defaultdict(set)
            for s in swarms_db:
                result[s.token_address].add(s.whale_address)
            
            db.close()
            if result:
                 self.logger.info(f"🔓 Restored {len(result)} active swarms from DB.")
            return result
        except Exception as e:
            self.logger.error(f"Error loading swarms from DB: {e}")
            return defaultdict(set)

    def _save_swarm_participant(self, token_address, whale_address):
        """Persist a single swarm participant mapping."""
        try:
            from database import SessionLocal
            from models import ActiveSwarm
            
            db = SessionLocal()
            # Check if exists
            exists = db.query(ActiveSwarm).filter(
                ActiveSwarm.token_address == token_address,
                ActiveSwarm.whale_address == whale_address
            ).first()
            
            if not exists:
                new_entry = ActiveSwarm(token_address=token_address, whale_address=whale_address)
                db.add(new_entry)
                db.commit()
            
            db.close()
        except Exception:
            # Silence DB spam - swarms are still processed in memory
            pass

    def _delete_swarm_from_db(self, token_address):
        """Remove all participants for a token from DB (on exit)."""
        try:
            from database import SessionLocal
            from models import ActiveSwarm
            
            db = SessionLocal()
            db.query(ActiveSwarm).filter(ActiveSwarm.token_address == token_address).delete()
            db.commit()
            db.close()
        except Exception:
            pass

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
            
            # ✅ LOG SUCCESS/FAILURE
            if result:
                self.logger.info(f"✅ Loaded {len(result)} whale wallets from DB.")
            else:
                self.logger.warning("⚠️ No whale wallets found in DB. Starting fresh.")
            
            return result
        except Exception as e:
            self.logger.error(f"❌ Error loading wallets from DB: {e}")
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
                    stats=data.get('stats'),
                    discovered_on=data.get('discovered_on'),
                    score=data.get('score', 10.0)
                )
                db.add(new_wallet)
                self.logger.info(f"💾 Saved new whale to DB: {address[:16]}...")
            else:
                existing.stats = data.get('stats') # Update stats
            
            db.commit()
            db.close()
        except Exception as e:
            self.logger.error(f"❌ Error saving whale to DB: {e}")


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

    def scan_market_for_whales_sync(self, max_pairs=10, max_traders_per_pair=5):
        """
        SYNC version of whale scanner - runs in thread to avoid blocking Discord.
        """
        self.logger.info("🌊 Starting Whale Hunt (Sync)...")
        
        # 1. Get Trending Pairs (sync call)
        import requests
        try:
            resp = requests.get("https://api.dexscreener.com/token-boosts/top/v1", timeout=10)
            if resp.status_code != 200:
                return 0
            pairs = resp.json()[:max_pairs]
        except Exception as e:
            self.logger.error(f"Error fetching trending: {e}")
            return 0
            
        self.logger.info(f"🔎 Found {len(pairs)} trending pairs to scan.")
        
        new_wallets = 0
        
        for pair in pairs:
            token_address = pair.get('tokenAddress')
            if not token_address: continue
            
            self.logger.info(f"  👉 Scanning {token_address[:16]}...")
            
            # 2. Get Recent Signatures (Trades)
            sigs = self.collector.get_signatures_for_address(token_address, limit=50)
            if not sigs: continue
            
            sig_list = [s['signature'] for s in sigs]
            
            # 3. Parse Transactions to find Signers
            parsed_txs = self.collector.batch_fetch_parsed_txs(sig_list)
            
            traders = set()
            for tx in parsed_txs:
                if tx.get('type') == 'SWAP':
                    payer = tx.get('feePayer')
                    if payer:
                        traders.add(payer)
            
            self.logger.info(f"    found {len(traders)} unique traders.")
            
            # 4. Analyze Each Trader
            checked_count = 0
            for wallet in traders:
                if checked_count >= max_traders_per_pair: break
                if wallet in self.qualified_wallets:
                    continue
                
                stats = self.collector.analyze_wallet(wallet, lookback_txs=50)
                checked_count += 1
                
                if stats and stats.get('is_qualified'):
                    self.logger.info(f"    🔥 FOUND QUALIFIED TRADER: {wallet}")
                    wallet_data = {
                        "discovered_on": token_address[:16],
                        "discovered_at": datetime.now().isoformat(),
                        "stats": stats,
                        "score": 10
                    }
                    self.qualified_wallets[wallet] = wallet_data
                    new_wallets += 1
                    self._save_wallet_to_db(wallet, wallet_data)
                    
        if len(self.qualified_wallets) > 100:
            self._prune_old_whales()
            
        self.logger.info(f"✅ Hunt Complete. Found {new_wallets} new qualified wallets. Total: {len(self.qualified_wallets)}")
        return new_wallets

    async def monitor_swarm(self, window_minutes=10, min_buyers=3):
        """
        Real-time Swarm Detector.
        Polls all Qualified Wallets.
        Returns list of (token_mint, token_symbol) to BUY.
        """
        if not self.qualified_wallets:
            return []
            
        signals = []
        cluster = defaultdict(set) # token_mint -> {wallet_addresses}
        
        # Optimize: Round-Robin Scanning (10 wallets per cycle)
        # Prevents API Credit Drain (2M -> 100k per day)
        
        all_wallets = list(self.qualified_wallets.keys())
        batch_size = 15 # Restore Coverage: Batch size increased because checks are now 90% cheaper
        total_wallets = len(all_wallets)
        
        if total_wallets == 0: return []
        
        start_idx = self._scan_index % total_wallets
        # Handle wrap-around
        if start_idx + batch_size > total_wallets:
             batch = all_wallets[start_idx:] + all_wallets[:(start_idx + batch_size - total_wallets)]
        else:
             batch = all_wallets[start_idx : start_idx + batch_size]
             
        self._scan_index = (self._scan_index + batch_size) % total_wallets
        
        self.logger.info(f"👀 Swarm Scan: Checking batch {start_idx}-{start_idx+batch_size} ({len(batch)} whales)...")
        
        # 1. Check batch wallets for recent activity
        for wallet in batch:
            # CHEAP CHECK: Get latest signature first (1 credit)
            latest_sig = await self.collector.get_latest_signature_async(wallet)
            
            if latest_sig:
                if self._last_signatures.get(wallet) == latest_sig:
                    continue
                self._last_signatures[wallet] = latest_sig
            
            # EXPENSIVE CHECK: Fetch last 10 txs ONLY if signature changed
            txs = await self.collector.fetch_helius_history_async(wallet, limit=10)
            if txs:
                self.process_transactions(txs, window_minutes=window_minutes)

        # 2. ANALYZE cache for swarms
        return self.analyze_swarms(min_buyers=min_buyers, window_minutes=window_minutes)

    def process_transactions(self, transactions, window_minutes=60):
        """Processes a list of transactions and updates the recent activity cache."""
        now = datetime.utcnow()
        added_count = 0
        
        for tx in transactions:
            ts = tx.get('timestamp', 0)
            if not ts: continue
            
            tx_time = datetime.utcfromtimestamp(ts)
            age_min = (now - tx_time).total_seconds() / 60
            
            if age_min > window_minutes:
                continue
            
            # Identify the wallet (signer)
            wallet = tx.get('feePayer')
            if not wallet:
                # Fallback: Find the user account in transfers
                transfers = tx.get('tokenTransfers', [])
                if transfers:
                    wallet = transfers[0].get('fromUserAccount')

            if not wallet: continue

            transfers = tx.get('tokenTransfers', [])
            tokens_in = [t.get('mint') for t in transfers if t.get('toUserAccount') == wallet]
            
            SOL_MINT = "So11111111111111111111111111111111111111112"
            USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
            STABLE_MINTS = {SOL_MINT, USDC_MINT, "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB", "USD1ttGY1N17NEEHLmELoaybftRBUSErhqYiQzvEmuB"}

            for mint in tokens_in:
                if mint in STABLE_MINTS: continue
                
                tx_sig = tx.get('signature', '')
                if tx_sig in self._processed_signatures:
                    continue
                
                # self.logger.debug(f"    👉 Activity: {mint[:8]} bought by {wallet[:8]}")
                self._recent_whale_activity.append({
                    'wallet': wallet,
                    'mint': mint,
                    'timestamp': tx_time,
                    'signature': tx_sig
                })
                self._processed_signatures.add(tx_sig)
                added_count += 1
        return added_count

    def analyze_swarms(self, min_buyers=3, window_minutes=60):
        """Analyzes recent activity for swarms."""
        signals = []
        now = datetime.utcnow()
        
        # 1. PRUNE
        self._recent_whale_activity = [
            x for x in self._recent_whale_activity 
            if (now - x['timestamp']).total_seconds() / 60 <= window_minutes
        ]
        
        # Sync signatures set with pruned list
        self._processed_signatures = {x['signature'] for x in self._recent_whale_activity}
        
        # 2. CLUSTER
        cluster = defaultdict(set)
        for entry in self._recent_whale_activity:
            cluster[entry['mint']].add(entry['wallet'])
            
        # 3. FILTER
        for mint, buyers in cluster.items():
            if len(buyers) >= min_buyers:
                if mint in self.active_swarms:
                    continue
                    
                self.logger.info(f"🚀 SWARM DETECTED: {len(buyers)} whales bought {mint}")
                signals.append(mint)
                self.active_swarms[mint] = buyers
                for whale in buyers:
                    self._save_swarm_participant(mint, whale)
                    
        return signals

    def detect_whale_sells(self, transactions, held_tokens):
        """
        Detect if any tracked whale is SELLING a token we currently hold.
        Returns list of token mints where sells were detected.
        
        Args:
            transactions: List of Helius Enhanced Transactions
            held_tokens: Set of token mints we currently hold positions in
        """
        sell_signals = []
        if not held_tokens:
            return sell_signals
            
        SOL_MINT = "So11111111111111111111111111111111111111112"
        USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
        STABLE_MINTS = {SOL_MINT, USDC_MINT, "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"}
        
        for tx in transactions:
            wallet = tx.get('feePayer')
            if not wallet:
                continue
                
            # Only care about tracked whales
            if wallet not in self.qualified_wallets:
                continue
                
            transfers = tx.get('tokenTransfers', [])
            
            # Check for SELL: Whale sends token OUT, receives SOL/USDC IN
            for t in transfers:
                if t.get('fromUserAccount') == wallet:
                    sold_mint = t.get('mint')
                    if sold_mint and sold_mint in held_tokens:
                        self.logger.warning(f"📉 WHALE SELL DETECTED: {wallet[:8]}... sold {sold_mint[:8]}...")
                        if sold_mint not in sell_signals:
                            sell_signals.append(sold_mint)
                            
        return sell_signals



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
        for wallet in list(participants):  # Copy to avoid mutation
            # Check recent history for SELL of this token (Last 10 txs)
            txs = await self.collector.fetch_helius_history_async(wallet, limit=10)
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
            # CLEANUP DB
            self._delete_swarm_from_db(token_mint)
            if token_mint in self.active_swarms:
                del self.active_swarms[token_mint]
            return True
            
        return False

    async def search_participants_for_token(self, token_mint, window_minutes=360):
        """
        Heuristic: Search through ALL qualified wallets to see who bought this token recently.
        Used to 'heal' positions after a restart if the swarm was lost.
        window_minutes: default 6 hours.
        """
        if not self.qualified_wallets: return set()
        
        self.logger.info(f"🩹 Healing: Searching participants for {token_mint[:8]}...")
        found_whales = set()
        
        # We don't want to scan ALL 100+ whales in one go if we can help it,
        # but for a ONE-TIME startup healing, it's worth the credits.
        # We'll batch them to avoid hitting Helius too hard.
        all_wallets = list(self.qualified_wallets.keys())
        
        for i in range(0, len(all_wallets), 10):
            batch = all_wallets[i:i+10]
            tasks = []
            for wallet in batch:
                tasks.append(self.collector.fetch_helius_history_async(wallet, limit=10))
            
            results = await asyncio.gather(*tasks)
            
            now = datetime.utcnow()
            for wallet, txs in zip(batch, results):
                if not txs: continue
                for tx in txs:
                    ts = tx.get('timestamp', 0)
                    if not ts: continue
                    tx_time = datetime.utcfromtimestamp(ts)
                    if (now - tx_time).total_seconds() / 60 > window_minutes:
                        continue
                        
                    # Check if BUY
                    transfers = tx.get('tokenTransfers', [])
                    for t in transfers:
                        if t.get('toUserAccount') == wallet and t.get('mint') == token_mint:
                            found_whales.add(wallet)
                            break
            
            await asyncio.sleep(0.5) # Tiny breather between batches
            
        if found_whales:
            self.logger.info(f"🩹 Healed: Found {len(found_whales)} whales for {token_mint[:8]}")
        return found_whales
