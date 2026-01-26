import asyncio
import logging
import json
import os
import random
import time
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
        # DB Persistence (Initialized as empty, filled via load_data)
        self.qualified_wallets = {}
        self.active_swarms = defaultdict(set)
        self._last_signatures = {} # Cache for {wallet: signature}
        self._recent_whale_activity = [] # List of {wallet, mint, timestamp, signature}
        self._processed_signatures = set() # O(1) duplicate checking
        self._scan_index = 0
        self._last_429_time = 0
        self._cumulative_exits = defaultdict(set)  # mint -> {wallets who sold}
        self.whale_persistence_hours = 48  # Default, updated by AlertSystem config
        self._unqualified_cache = {} # {address: cleanup_timestamp} - Save credits on known bad wallets


    def load_data(self):
        """Heavy lifting: Load wallets and swarms from DB."""
        self.qualified_wallets = self._load_wallets()
        self.active_swarms = self._load_swarms()
        self.logger.info("📦 SmartCopyTrader data loaded successfully.")

    def _load_swarms(self):
        """Restore active swarm participants from DB."""
        try:
            from database import SessionLocal
            from models import ActiveSwarm
            
            for attempt in range(3):
                try:
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
                    if attempt < 2:
                        self.logger.warning(f"⚠️ DB Load attempt {attempt+1} failed, retrying in 2s...")
                        import time
                        time.sleep(2)
                    else:
                        self.logger.error(f"Error loading swarms from DB: {e}")
            return defaultdict(set)
        except Exception as e:
            self.logger.error(f"❌ CRITICAL: Failed to initialize swarm loading: {e}")
            return defaultdict(set)

    def _save_swarm_participant(self, token_address, whale_address):
        """Persist a single swarm participant mapping."""
        for attempt in range(3):
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
                return # Success
            except Exception as e:
                if "SSL connection" in str(e) and attempt < 2:
                    import time
                    time.sleep(2)
                else:
                    self.logger.error(f"Error saving swarm participant to DB: {e}")
                    break

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
            
            for attempt in range(3):
                try:
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
                    if result:
                        self.logger.info(f"✅ Loaded {len(result)} whale wallets from DB.")
                    else:
                        self.logger.warning("⚠️ No whale wallets found in DB. Starting fresh.")
                    return result
                except Exception as e:
                    if "SSL connection" in str(e) and attempt < 2:
                        self.logger.warning(f"⚠️ DB SSL Drop during wallet load. Retrying {attempt+1}/3...")
                        import time
                        time.sleep(2) # Sync sleep because this is often called during init
                    else:
                        self.logger.error(f"❌ Error loading wallets from DB: {e}")
                        break
            return {}
        except Exception as e:
            self.logger.error(f"❌ CRITICAL: Failed to initialize wallet loading: {e}")
            return {}
    
    def update_whale_score(self, address, delta):
        """Increase or decrease a whale's score based on trade outcome."""
        if address in self.qualified_wallets:
            old_score = self.qualified_wallets[address].get('score', 10.0)
            # ULTIMATE BOT: ASYMMETRIC SCORING
            # Losses hurt more than wins to prune "churny" alpha
            adj_delta = delta if delta > 0 else (delta * 2.5)
            new_score = max(0.0, old_score + adj_delta)
            self.qualified_wallets[address]['score'] = new_score
            
            # Sync to DB
            for attempt in range(3):
                try:
                    from database import SessionLocal
                    from models import WhaleWallet
                    db = SessionLocal()
                    existing = db.query(WhaleWallet).filter(WhaleWallet.address == address).first()
                    if existing:
                        existing.score = new_score
                        db.commit()
                    db.close()
                    return new_score # Success
                except Exception as e:
                    if "SSL connection" in str(e) and attempt < 2:
                        import time
                        time.sleep(2)
                    else:
                        break
            
            return new_score
        return None

    def _save_wallet_to_db(self, address, data):
        """Save a single wallet to DB."""
        for attempt in range(3):
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
                return # Success
            except Exception as e:
                if "SSL connection" in str(e) and attempt < 2:
                    import time
                    time.sleep(2)
                else:
                    self.logger.error(f"❌ Error saving whale to DB: {e}")
                    break


    def _prune_old_whales(self, keep_count=500):
        """Remove oldest whales to keep list fresh. Capacity increased to 500."""
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
                    
        # Pruning: Keep only top 500 whales (by score/freshness)
        if len(self.qualified_wallets) > 500:
            self._prune_old_whales()
            
            # Respect rate limits
            await asyncio.sleep(1) 
            
        self.logger.info(f"✅ Hunt Complete. Found {new_wallets} new qualified wallets. Total: {len(self.qualified_wallets)}")
        return new_wallets

    def scan_market_for_whales_sync(self, max_pairs=10, max_traders_per_pair=3):
        """
        SYNC version of whale scanner - runs in thread to avoid blocking Discord.
        Optimized: Reduced depth to save Helius credits.
        """
        self.logger.info("🌊 Starting Whale Hunt (Sync)...")
        
        # 1. Get Trending Pairs (sync call) with retry and fallback
        import requests
        pairs = []
        try:
            # TRY 1 & 2: Token Profiles (Deep Discovery)
            for attempt in range(2):
                resp = requests.get("https://api.dexscreener.com/token-profiles/latest/v1", timeout=10)
                if resp.status_code == 200:
                    data = resp.json()
                    pairs = [p for p in data if p.get('chainId') == 'solana'][:max_pairs]
                    break
                elif resp.status_code == 429:
                    if time.time() - self._last_429_time > 60:
                        self.logger.warning(f"🛑 DexScreener Profiles 429 (Attempt {attempt+1}). {'Retrying in 5s...' if attempt == 0 else 'Falling back to Trending API.'}")
                        self._last_429_time = time.time()
                    if attempt == 0: time.sleep(5)
                else:
                    break

            # FALLBACK: DexScreener Search API (High reliability for Solana)
            if not pairs:
                self.logger.info("🔄 Falling back to Search API for whale hunt...")
                # Search for Solana pairs (broad query)
                resp = requests.get("https://api.dexscreener.com/latest/dex/search?q=solana", timeout=10)
                if resp.status_code == 200:
                    data = resp.json()
                    # Standard API returns {'pairs': [...]}
                    pairs = (data.get('pairs') or [])[:max_pairs]
                else:
                    self.logger.error(f"❌ Both Profiles and Search APIs failed (Status: {resp.status_code})")
                    return 0
        except Exception as e:
            self.logger.error(f"Error fetching trending: {e}")
            return 0
            
        self.logger.info(f"🔎 Found {len(pairs)} trending pairs to scan.")
        
        new_wallets = 0
        
        for pair in pairs:
            # Normalize Token Address (Profiles vs Pairs API structure)
            token_address = pair.get('tokenAddress') or pair.get('baseToken', {}).get('address')
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
                        # CREDIT OPTIMIZATION: Check skip cache
                        now = time.time()
                        if payer in self._unqualified_cache:
                            if now < self._unqualified_cache[payer]:
                                continue # Still in 24h penalty box
                            else:
                                del self._unqualified_cache[payer] # Cooldown expired
                        traders.add(payer)
            
            self.logger.info(f"    found {len(traders)} unique traders (after filtering cached).")
            
            # 4. Analyze Each Trader
            checked_count = 0
            for wallet in traders:
                if checked_count >= max_traders_per_pair: break
                if wallet in self.qualified_wallets:
                    continue
                
                # CREDIT OPTIMIZATION: Lower lookback for discovery screening
                stats = self.collector.analyze_wallet(wallet, lookback_txs=20)
                checked_count += 1
                
                # ALL TRADERS NOW ALLOWED (Alpha Unlock)
                if stats and stats.get('is_qualified'):
                    self.logger.info(f"    🔥 FOUND ALPHA WHALE: {wallet}")
                    wallet_data = {
                        "discovered_on": token_address[:16],
                        "discovered_at": datetime.now().isoformat(),
                        "stats": stats,
                        "score": 12.5 # HUNTER BONUS: Fresh PNL-verified whales start stronger
                    }
                    self.qualified_wallets[wallet] = wallet_data
                    new_wallets += 1
                    self._save_wallet_to_db(wallet, wallet_data)
                else:
                    # CREDIT OPTIMIZATION: Cache failures for 24h
                    self._unqualified_cache[wallet] = time.time() + 86400
                    
        if len(self.qualified_wallets) > 500:
            self._prune_old_whales()
            
        self.logger.info(f"✅ Hunt Complete. Found {new_wallets} new qualified wallets. Total: {len(self.qualified_wallets)}")
        return new_wallets

    async def monitor_swarm(self, window_minutes=10, min_buyers=3):
        """
        Real-time Swarm Detector.
        Polls all Qualified Wallets.
        Window increased to 15m to catch more swarms.
        Returns list of (token_mint, token_symbol) to BUY.
        """
        if not self.qualified_wallets:
            return []
            
        signals = []
        cluster = defaultdict(set) # token_mint -> {wallet_addresses}
        
        # Optimize: Round-Robin Scanning (10 wallets per cycle)
        # Prevents API Credit Drain (2M -> 100k per day)
        
        all_wallets = list(self.qualified_wallets.keys())
        batch_size = 50 # Increased from 25 to reduce scan lag for large pools
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

    def process_transactions(self, transactions, window_minutes=10):
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

    def analyze_swarms(self, min_buyers=3, window_minutes=10, held_tokens=None):
        """Analyzes recent activity for swarms.
        
        Args:
            held_tokens: Set of token mints we currently hold. These swarms will NOT be pruned
                         even if activity expires, to prevent false positive orphan detection.
        """
        signals = []
        now = datetime.utcnow()
        held_tokens = held_tokens or set()
        
        # 1. PRUNE RECENT ACTIVITY
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
        
        # 🔍 SWARM PRUNING (Phase 42 Improvement)
        # Remove tokens from active_swarms (and DB) if they no longer meet the threshold
        # CRITICAL: Don't prune swarms for tokens we still hold (prevents false orphan exits)
        active_mint_list = list(self.active_swarms.keys())
        for mint in active_mint_list:
            # SKIP PRUNING if we still hold this token
            if mint in held_tokens:
                continue
                
            if cluster.get(mint, set()) == set(): # No activity at all in the window
                self.logger.info(f"🧹 Pruning dead swarm: {mint[:16]}... (cooled down)")
                if mint in self.active_swarms:
                    del self.active_swarms[mint]
                # Cleanup DB so it doesn't restore on next reboot
                self._delete_swarm_from_db(mint)


        # 🔍 DIAGNOSTIC: Show top tokens by whale interest
        if cluster:
            sorted_tokens = sorted(cluster.items(), key=lambda x: len(x[1]), reverse=True)[:3]
            top_info = ", ".join([f"{m[:8]}...({len(w)} whales)" for m, w in sorted_tokens])
            # Show Near Swarms vs Potential Swarms based on dynamic min_buyers
            if sorted_tokens:
                main_token = sorted_tokens[0]
                if len(main_token[1]) >= min_buyers:
                    self.logger.info(f"📊 Potential Swarms: {top_info}")
                elif len(main_token[1]) == (min_buyers - 1):
                    self.logger.info(f"👀 Near Swarm ({min_buyers-1}/{min_buyers}): {top_info}")
                else:
                    self.logger.debug(f"📊 Market Activity: {top_info}")
            
        # 3. FILTER / SIGNAL
        for mint, buyers in cluster.items():
            if len(buyers) >= min_buyers:
                if mint in self.active_swarms:
                    continue
                
                # 🎯 SMART WHALE FILTERING (Sustainable Growth V2)
                # Only count whales who are:
                # 1. Active for at least 48 hours (not bot-spam)
                # 2. Have positive score (historical wins > losses)
                qualified_buyers = set()
                for wallet in buyers:
                    whale_data = self.qualified_wallets.get(wallet, {})
                    
                    # Check persistence (Dynamic minimum)
                    discovered_at = whale_data.get('discovered_at')
                    if discovered_at:
                        try:
                            disc_time = datetime.fromisoformat(discovered_at)
                            age_hours = (now - disc_time).total_seconds() / 3600
                            if age_hours < self.whale_persistence_hours:
                                continue  # Too new, skip
                        except:
                            pass  # Can't parse, allow through
                    
                    # Check positive PNL (score > 0)
                    score = whale_data.get('score', 10.0)
                    if score <= 0:
                        continue  # Negative PNL history, skip
                    
                    qualified_buyers.add(wallet)
                
                # Re-check threshold after filtering
                if len(qualified_buyers) < min_buyers:
                    self.logger.info(f"⏭️ Filtered Swarm: {mint[:8]}... ({len(buyers)} raw, {len(qualified_buyers)} qualified)")
                    continue
                    
                self.logger.info(f"🚀 SWARM DETECTED: {len(qualified_buyers)} QUALIFIED whales bought {mint}")
                signals.append(mint)
                self.active_swarms[mint] = qualified_buyers
                for whale in qualified_buyers:
                    self._save_swarm_participant(mint, whale)
                    
        return signals

    def _delete_swarm_from_db(self, mint):
        """Removes a swarm and its participants from the database."""
        try:
            from database import SessionLocal
            from models import ActiveSwarm
            db = SessionLocal()
            db.query(ActiveSwarm).filter(ActiveSwarm.token_address == mint).delete()
            db.commit()
            db.close()
        except Exception as e:
            self.logger.error(f"Error pruning swarm from DB: {e}")

    def get_top_signals(self, limit=6):
        """
        Get top tokens by whale interest for frontend display.
        Returns list of dicts with token info and whale count.
        """
        from collections import defaultdict
        from datetime import datetime
        
        results = []
        now = datetime.utcnow()
        
        # Cluster recent activity by mint
        cluster = defaultdict(set)
        for entry in self._recent_whale_activity:
            # Only include recent activity (last 30 mins)
            if (now - entry['timestamp']).total_seconds() / 60 <= 30:
                cluster[entry['mint']].add(entry['wallet'])
        
        # Sort by whale count
        sorted_tokens = sorted(cluster.items(), key=lambda x: len(x[1]), reverse=True)[:limit]
        
        for mint, whales in sorted_tokens:
            # Try to get token info
            symbol = mint[:8] + '...'
            
            results.append({
                'mint': mint,
                'symbol': symbol,
                'whale_count': len(whales),
                'is_swarm': len(whales) >= 3,
                'price': 0,  # Could be fetched from DexScreener
                'liquidity': 0
            })
        
        return results


    def detect_whale_sells(self, transactions, held_tokens):
        """
        Detect if a CONSENSUS of ORIGINAL SWARM participants are SELLING a token we currently hold.
        Returns list of token mints where consensus sell threshold was met.
        
        CONSENSUS RULES:
        - Swarm 1-2: Exit on 1 sell (Fragile/Legacy)
        - Swarm 3-4: Exit on 2 sells
        - Swarm 5+: Exit on 50% sells
        
        Args:
            transactions: List of Helius Enhanced Transactions
            held_tokens: Set of token mints we currently hold positions in
        """
        if not held_tokens:
            return []
            
        # Initialize seller tracking if not present (transient per call batch)
        # Note: We don't want to persist this across batches because transactions
        # in a single batch represent a specific point in time. 
        # However, for REAL consensus, we actually need to look at who HAS sold
        # in the recent history.
            
        detected_mint_exits = []
        
        # 1. Identify which whales from which swarms are selling in this batch
        # AND add them to CUMULATIVE tracking (persists across batches)
        for tx in transactions:
            wallet = tx.get('feePayer')
            if not wallet or wallet not in self.qualified_wallets:
                continue
                
            transfers = tx.get('tokenTransfers', [])
            for t in transfers:
                if t.get('fromUserAccount') == wallet:
                    sold_mint = t.get('mint')
                    if sold_mint and sold_mint in held_tokens:
                        # Is this whale part of the original swarm?
                        swarm_participants = self.active_swarms.get(sold_mint, set())
                        if wallet in swarm_participants:
                            # Add to CUMULATIVE tracker (survives across batches!)
                            self._cumulative_exits[sold_mint].add(wallet)
                            self.logger.info(f"📉 WHALE EXIT TRACKED: {wallet[:8]}... sold {sold_mint[:8]}... ({len(self._cumulative_exits[sold_mint])} total exits)")
        
        # 2. EVALUATE CONSENSUS using CUMULATIVE exits (not just this batch)
        for mint in list(self._cumulative_exits.keys()):
            if mint not in held_tokens:
                continue
                
            participants = self.active_swarms.get(mint, set())
            swarm_size = len(participants)
            cumulative_seller_count = len(self._cumulative_exits[mint])
            
            # Calculate threshold (Ultimate Bot: "Diamond Hands" Consensus)
            # For 1-2 whale swarms, exit on FIRST sell (we're following alphas)
            threshold = 1
            if swarm_size >= 5:
                threshold = max(2, swarm_size // 2)  # 50% for large swarms
            elif swarm_size >= 3:
                threshold = 2  # 2/3+ for medium swarms
            # For swarms of 1-2, threshold stays at 1 (follow the alpha immediately)
                
            if cumulative_seller_count >= threshold:
                self.logger.warning(f"📉 CONSENSUS SELL MET: {cumulative_seller_count}/{swarm_size} whales sold {mint[:8]}... (CUMULATIVE)")
                detected_mint_exits.append(mint)
                # Clean up the tracker for this mint
                del self._cumulative_exits[mint]
            else:
                self.logger.info(f"⏳ Whale exit {cumulative_seller_count}/{threshold} for {mint[:8]}... (waiting for more exits)")
                            
        return detected_mint_exits



    def prune_lazy_whales(self, inactive_hours=24):
        """
        Remove whales who haven't traded in X hours.
        Returns count of pruned whales.
        ULTRA-HARDENED: Batch deletes with retry logic.
        """
        try:
            from database import SessionLocal
            import models
            from datetime import datetime, timedelta
            import time
            
            db = SessionLocal()
            cutoff = datetime.utcnow() - timedelta(hours=inactive_hours)
            
            # Find lazy whales (no last_active or older than cutoff)
            lazy_whales = db.query(models.WhaleWallet).filter(
                (models.WhaleWallet.last_active < cutoff) | 
                (models.WhaleWallet.last_active == None)
            ).all()
            
            pruned_count = 0
            
            # BATCH DELETE: Process in groups of 50 to avoid transaction timeouts
            batch_size = 50
            for i in range(0, len(lazy_whales), batch_size):
                batch = lazy_whales[i:i + batch_size]
                
                for attempt in range(3):  # 3 retries
                    try:
                        for whale in batch:
                            address = whale.address
                            
                            # Remove from memory
                            if address in self.qualified_wallets:
                                del self.qualified_wallets[address]
                            
                            # Remove from DB
                            db.delete(whale)
                            pruned_count += 1
                        
                        db.commit()
                        break  # Success, exit retry loop
                        
                    except Exception as e:
                        db.rollback()
                        if "SSL connection" in str(e) and attempt < 2:
                            self.logger.warning(f"⚠️ DB SSL Drop during prune. Retrying {attempt + 1}/3...")
                            time.sleep(2)
                            # Reconnect
                            db.close()
                            db = SessionLocal()
                        else:
                            self.logger.error(f"❌ Failed to prune batch: {e}")
                            break
            
            db.close()
            
            if pruned_count > 0:
                self.logger.info(f"🧹 Pruned {pruned_count} lazy whales (inactive > {inactive_hours}h)")
            
            return pruned_count
            
        except Exception as e:
            self.logger.error(f"❌ Error pruning whales: {e}")
            return 0

    
    def update_whale_activity(self, wallet_address):
        """Update last_active timestamp for a whale when we see them trade.
        ULTRA-HARDENED: Retry with SSL recovery."""
        if wallet_address not in self.qualified_wallets:
            return
            
        for attempt in range(3):
            try:
                from database import SessionLocal
                import models
                from datetime import datetime
                
                db = SessionLocal()
                whale = db.query(models.WhaleWallet).filter(
                    models.WhaleWallet.address == wallet_address
                ).first()
                
                if whale:
                    whale.last_active = datetime.utcnow()
                    db.commit()
                db.close()
                return  # Success
                
            except Exception as e:
                if "SSL connection" in str(e) and attempt < 2:
                    import time
                    time.sleep(1)
                    continue
                # Silent fail - activity tracking is non-critical
                return



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

    async def scan_market_for_whales(self, max_pairs=5, max_traders_per_pair=3):
        """
        ULTIMATE WHALE HUNT: Finds the 50 best whales of the last 24h.
        1. Gets trending Solana pairs.
        2. Inspects top buyers.
        3. Qualifies them via Helius.
        """
        print(f"🦈 Ultimate Hunt: Scanning market for fresh Alpha...")
        try:
            # 1. Get Trending Tokens
            trending = await self.dex_scout.get_trending_solana_pairs(limit=max_pairs)
            if not trending: return 0
            
            new_found = 0
            for pair in trending[:max_pairs]:
                mint = pair.get('baseToken', {}).get('address')
                if not mint: continue
                
                # 2. Get Recent Signatures for this token
                sigs = self.collector.crawl_token(mint)
                if not sigs: continue
                
                # Extract unique signers from first 50 sigs (parsed)
                # Note: collector.crawl_token returns sig objects, need to fetch parsed txs
                parsed_txs = self.collector.batch_fetch_parsed_txs([s.get('signature') for s in sigs[:50]])
                if not parsed_txs: continue
                
                potential_whales = set()
                for tx in parsed_txs:
                    signer = tx.get('feePayer') # Usually the signer
                    if signer and signer not in self.qualified_wallets:
                        potential_whales.add(signer)
                
                # 3. Qualify them
                for wallet in list(potential_whales)[:max_traders_per_pair]:
                    analysis = self.collector.analyze_wallet(wallet)
                    if analysis.get('is_qualified'):
                        score = 15.0 # New whales start with bonus score to prove themselves
                        self.qualified_wallets[wallet] = {
                            "score": score,
                            "discovered_on": mint,
                            "stats": analysis
                        }
                        self._save_wallet_to_db(wallet, self.qualified_wallets[wallet])
                        new_found += 1
                        print(f"🦈 Hunt Found: {wallet[:12]}... (Qualified Alpha)")
            
            # 4. Prune if we have too many (Keep best 500)
            if len(self.qualified_wallets) > 500:
                await self.replace_lazy_whales(limit=100)
                
            return new_found
        except Exception as e:
            self.logger.error(f"Error during whale hunt: {e}")
            return 0

    async def replace_lazy_whales(self, limit=50):
        """Prunes the lowest scoring whales to make room for fresh ones."""
        # Lower threshold to 100 to keep the alpha pool fresh and rotating
        if len(self.qualified_wallets) < 100: return
        
        # Sort by score ascending
        sorted_whales = sorted(self.qualified_wallets.items(), key=lambda x: x[1].get('score', 10.0))
        to_prune = sorted_whales[:limit]
        
        for addr, data in to_prune:
            del self.qualified_wallets[addr]
            try:
                from database import SessionLocal
                from models import WhaleWallet
                db = SessionLocal()
                db.query(WhaleWallet).filter(WhaleWallet.address == addr).delete()
                db.commit()
                db.close()
            except: pass
            
        print(f"🧹 Pruned {len(to_prune)} lazy whales from the pool.")
