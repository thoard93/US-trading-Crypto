import asyncio
import logging
import json
import os
import random
from datetime import datetime
from backend.collectors.dex_scout import DexScout
from backend.collectors.wallet_collector import WalletCollector

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
        self.wallets_file = os.path.join(os.path.dirname(__file__), "../data/qualified_wallets.json")
        self.ensure_data_dir()
        self.qualified_wallets = self._load_wallets()
        self.active_swarms = {} # token_mint -> set(wallet_addresses)

    def ensure_data_dir(self):
        os.makedirs(os.path.dirname(self.wallets_file), exist_ok=True)

    def _load_wallets(self):
        if os.path.exists(self.wallets_file):
            try:
                with open(self.wallets_file, 'r') as f:
                    return json.load(f)
            except:
                return {}
        return {}
    
    def _save_wallets(self):
        with open(self.wallets_file, 'w') as f:
            json.dump(self.qualified_wallets, f, indent=2)

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
                    self.qualified_wallets[wallet] = {
                        "discovered_on": symbol,
                        "discovered_at": datetime.now().isoformat(),
                        "stats": stats,
                        "score": 10 # Base Score
                    }
                    new_wallets += 1
                    self._save_wallets()
            
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
        
        # 1. Check each wallet for recent activity
        for wallet in self.qualified_wallets:
            # Fetch last 10 txs
            txs = self.collector.fetch_helius_history(wallet, limit=10)
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
