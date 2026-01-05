import requests
import time
import logging
import os
from datetime import datetime
from collections import defaultdict

class WalletCollector:
    """
    The 'Crawler' for Phase 16.
    Fetches transaction history from Solana RPC to identify 'Qualified Wallets'.
    """
    def __init__(self):
        self.rpc_url = os.getenv('SOLANA_RPC_URL', 'https://api.mainnet-beta.solana.com')
        self.helius_key = os.getenv('HELIUS_API_KEY') # User needs to provide this
        self.logger = logging.getLogger(__name__)
        self.last_request_time = 0
        self.request_interval = 0.5 

        if self.helius_key:
            self.rpc_url = f"https://mainnet.helius-rpc.com/?api-key={self.helius_key}"
        
    def _rpc_call(self, method, params):
        """Helper for raw JSON-RPC calls."""
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
            "params": params
        }
        try:
            # We don't need strict rate limiting if using Helius RPC (high limits)
            response = requests.post(self.rpc_url, json=payload, timeout=10)
            if response.status_code == 200:
                return response.json().get('result')
            else:
                self.logger.error(f"RPC Error {response.status_code}: {response.text}")
                return None
        except Exception as e:
            self.logger.error(f"RPC Exception: {e}")
            return None

    def get_signatures_for_address(self, address, limit=1000):
        """Fetch transaction signatures for a wallet or pair."""
        return self._rpc_call("getSignaturesForAddress", [
            address,
            {"limit": limit}
        ])

    def fetch_helius_history(self, address, limit=100):
        """
        Fast history fetch using Helius API.
        Returns PARSED transactions (much easier to analyze).
        """
        if not self.helius_key:
            self.logger.warning("🚫 No HELIUS_API_KEY found. History analysis will be slow/impossible.")
            return None
            
        url = f"https://api.helius.xyz/v0/addresses/{address}/transactions"
        params = {
            "api-key": self.helius_key,
            "type": "SWAP", # Filter for swaps only (cuts down noise)
            "limit": limit
        }
        
        try:
            resp = requests.get(url, params=params, timeout=10)
            if resp.status_code == 200:
                return resp.json()
            else:
                self.logger.error(f"Helius Error {resp.status_code}: {resp.text}")
                return None
        except Exception as e:
            self.logger.error(f"Helius Exception: {e}")
            return None

    def batch_fetch_parsed_txs(self, signatures):
        """
        Fetches parsed details for a batch of signatures (Max 100).
        Used to identify the 'Signer' (Wallet) of a trade.
        """
        if not self.helius_key or not signatures:
            return []
            
        url = f"https://api.helius.xyz/v0/transactions"
        params = {"api-key": self.helius_key}
        
        # Chunk into batches of 100 (Helius limit)
        all_parsed = []
        
        for i in range(0, len(signatures), 100):
            chunk = signatures[i:i+100]
            try:
                payload = {"transactions": chunk}
                resp = requests.post(url, params=params, json=payload, timeout=15)
                if resp.status_code == 200:
                    all_parsed.extend(resp.json())
                else:
                    self.logger.error(f"Helius Batch Error {resp.status_code}: {resp.text}")
            except Exception as e:
                self.logger.error(f"Helius Batch Exception: {e}")
                
        return all_parsed

    def analyze_wallet(self, wallet_address, lookback_txs=100):
        """
        The 'Human Filter'.
        Calculates Win Rate and P10 Holding Time.
        """
        # 1. Try Helius First (Fast + Parsed)
        helius_data = self.fetch_helius_history(wallet_address, limit=lookback_txs)
        
        if helius_data:
            return self._analyze_helius_data(wallet_address, helius_data)
            
        # 2. Fallback to Slow RPC (Not implemented for deep analysis yet)
        self.logger.warning(f"⚠️ Falling back to slow RPC for {wallet_address} (Not recommended)")
        return {
            "address": wallet_address,
            "error": "Missing Helius Key",
            "is_qualified": False
        }

    def _analyze_helius_data(self, address, transactions):
        """
        Analyzes parsed Helius transactions to find 'Holding Time'.
        """
        inventory = defaultdict(list) # mint -> [buy_timestamps]
        holding_times = [] # list of seconds
        wins = 0
        losses = 0
        
        SOL_MINT = "So11111111111111111111111111111111111111112"
        USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
        STABLE_MINTS = {SOL_MINT, USDC_MINT, "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"} # USDT

        # Sort txs by time ASCENDING (Oldest first)
        transactions.sort(key=lambda x: x.get('timestamp', 0))
        
        for tx in transactions:
            ts = tx.get('timestamp', 0)
            if not ts: continue
            
            # Simple heuristic for SWAP direction
            transfers = tx.get('tokenTransfers', [])
            native = tx.get('nativeTransfers', [])
            
            # Check what came IN and what went OUT of the wallet
            tokens_in = []
            tokens_out = []
            
            for t in transfers:
                if t.get('toUserAccount') == address:
                    tokens_in.append(t.get('mint'))
                elif t.get('fromUserAccount') == address:
                    tokens_out.append(t.get('mint'))
            
            # Handle Native SOL (Helius puts it in nativeTransfers)
            # If native SOL came IN (Sell), check nativeTransfers
            # This is complex, focusing on Token Transfers is safer for MVP.
            # Usually a Swap has 1 Token In and 1 Token Out.
            
            if not tokens_in or not tokens_out:
                continue
                
            token_in = tokens_in[0]
            token_out = tokens_out[0]
            
            # BUY: Stable -> Token
            if token_out in STABLE_MINTS and token_in not in STABLE_MINTS:
                inventory[token_in].append({
                    'ts': ts,
                    'price': 0 # Placeholder: Would need price history for PnL
                })
                
            # SELL: Token -> Stable
            elif token_in in STABLE_MINTS and token_out not in STABLE_MINTS:
                # Find matching buy
                prev_buys = inventory[token_out]
                if prev_buys:
                    # FIFO (First In First Out)
                    buy_data = prev_buys.pop(0)
                    hold_time = ts - buy_data['ts']
                    if hold_time > 0:
                        holding_times.append(hold_time)
                        
                        # Win/Loss Check (Requires USD amounts which Helius provides in nativeTransfers usually)
                        # For MVP we just track holding time.
                        
        # Calc Stats
        if not holding_times:
            p10 = 0
            avg = 0
        else:
            holding_times.sort()
            # Manual P10 calculation to avoid numpy dependency
            index = int(len(holding_times) * 0.10)
            p10 = holding_times[index]
            avg = sum(holding_times) / len(holding_times)

        return {
            "address": address,
            "tx_count": len(transactions),
            "trade_count": len(holding_times),
            "avg_holding_time_sec": avg,
            "p10_holding_time_sec": p10,
            "is_qualified": p10 > 60 and len(holding_times) > 5 # Qualification Rule
        }

    def crawl_token(self, token_mint):
        """
        Finds buyers of a token.
        """
        signatures = self.get_signatures_for_address(token_mint, limit=500)
        if not signatures:
            return []
        
        buyers = set()
        # In a real implementation we would parse these to find unique signers
        # For now, just returning the count of activity
        return signatures
