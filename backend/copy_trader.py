"""
Copy Trader Module
Monitors successful whale wallets for buys and follows with small positions.
Uses Helius webhooks or polling for wallet change detection.
"""
import asyncio
import os
import logging
import time
import requests
from datetime import datetime
from typing import Dict, List, Optional, Callable

logger = logging.getLogger("CopyTrader")

# Top Pump.fun traders (from Dune Analytics - high PnL, consistent volume)
# These are known successful snipers/traders to follow
TOP_TRADERS = [
    {
        "address": "ARu4n5mFdZogZAravu7CcizaojWnS6oqka37gdLT5SZn",
        "name": "PumpGodSniper1",
        "notes": "$393M PnL - elite tier sniper"
    },
    {
        "address": "suqh5sHtr8HyJ7q8scBimULPkPpA557prMG47xCHQfK", 
        "name": "PumpGodSniper2",
        "notes": "$27M PnL - high volume, consistent"
    }
]

class CopyTrader:
    """
    Lightweight copy trading module.
    Monitors 1-2 elite wallets and follows their Pump.fun buys.
    """
    
    def __init__(self, market_sniper=None):
        self.market_sniper = market_sniper
        self.monitored_wallets = [w["address"] for w in TOP_TRADERS]
        self.wallet_names = {w["address"]: w["name"] for w in TOP_TRADERS}
        
        # Copy trading settings
        self.copy_amount_sol = float(os.getenv("COPY_TRADE_AMOUNT_SOL", "0.05"))  # Max per copy
        self.max_daily_copies = int(os.getenv("COPY_MAX_DAILY", "10"))  # Cap daily exposure
        self.copy_delay_seconds = float(os.getenv("COPY_DELAY_SEC", "2"))  # Delay before following
        
        # State tracking
        self.daily_copy_count = 0
        self.last_reset_date = datetime.now().date()
        self.recent_copies = {}  # mint -> timestamp (avoid duplicates)
        self.running = False
        
        # Helius API for wallet monitoring
        self.helius_api_key = os.getenv("HELIUS_API_KEY", "")
        self.helius_rpc = f"https://mainnet.helius-rpc.com/?api-key={self.helius_api_key}" if self.helius_api_key else None
        
        # Last known signatures per wallet (for polling)
        self.last_signatures = {addr: None for addr in self.monitored_wallets}
        
        logger.info(f"🎯 CopyTrader initialized - Monitoring {len(self.monitored_wallets)} wallets")
        for w in TOP_TRADERS:
            logger.info(f"   Following: {w['name']} ({w['address'][:8]}...)")
    
    def _reset_daily_counter(self):
        """Reset daily copy count at midnight."""
        today = datetime.now().date()
        if today > self.last_reset_date:
            self.daily_copy_count = 0
            self.last_reset_date = today
            logger.info("📆 Daily copy counter reset")
    
    async def start_monitoring(self):
        """Start wallet monitoring loop."""
        self.running = True
        logger.info("👀 Starting copy trader wallet monitoring...")
        
        # Use polling since Helius webhooks require external endpoint
        while self.running:
            try:
                self._reset_daily_counter()
                
                # Check if we've hit daily limit
                if self.daily_copy_count >= self.max_daily_copies:
                    logger.info(f"📊 Daily copy limit reached ({self.max_daily_copies})")
                    await asyncio.sleep(300)  # Wait 5min before checking again
                    continue
                
                # Poll each monitored wallet for recent transactions
                for wallet_addr in self.monitored_wallets:
                    await self._check_wallet_activity(wallet_addr)
                
                await asyncio.sleep(10)  # Poll every 10 seconds
                
            except asyncio.CancelledError:
                self.running = False
                return
            except Exception as e:
                logger.error(f"Copy trader error: {e}")
                await asyncio.sleep(30)
    
    async def _check_wallet_activity(self, wallet_addr: str):
        """Check wallet for recent Pump.fun buys."""
        if not self.helius_api_key:
            # Fallback to public RPC (limited)
            return await self._check_wallet_public_rpc(wallet_addr)
        
        try:
            # Use Helius enhanced transaction API
            url = f"https://api.helius.xyz/v0/addresses/{wallet_addr}/transactions?api-key={self.helius_api_key}&limit=5"
            
            response = requests.get(url, timeout=10)
            if response.status_code != 200:
                return
            
            txs = response.json()
            
            for tx in txs:
                await self._analyze_transaction(tx, wallet_addr)
                
        except Exception as e:
            logger.debug(f"Helius wallet check failed: {e}")
    
    async def _check_wallet_public_rpc(self, wallet_addr: str):
        """Fallback: Check wallet using public Solana RPC."""
        try:
            # Use public RPC to get recent signatures
            rpc_url = os.getenv("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com")
            
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getSignaturesForAddress",
                "params": [wallet_addr, {"limit": 5}]
            }
            
            response = requests.post(rpc_url, json=payload, timeout=10)
            data = response.json()
            
            if "result" not in data:
                return
            
            signatures = data["result"]
            
            # Check if we've seen these signatures before
            if signatures and signatures[0]["signature"] != self.last_signatures.get(wallet_addr):
                # New transaction(s) detected
                self.last_signatures[wallet_addr] = signatures[0]["signature"]
                
                # Analyze the newest transaction
                await self._analyze_signature(signatures[0]["signature"], wallet_addr)
                
        except Exception as e:
            logger.debug(f"Public RPC check failed for {wallet_addr[:8]}: {e}")
    
    async def _analyze_signature(self, signature: str, wallet_addr: str):
        """Analyze a transaction signature for Pump.fun buys."""
        try:
            rpc_url = os.getenv("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com")
            
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getTransaction",
                "params": [signature, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}]
            }
            
            response = requests.post(rpc_url, json=payload, timeout=10)
            data = response.json()
            
            if "result" not in data or not data["result"]:
                return
            
            tx = data["result"]
            
            # Check if this involves Pump.fun program
            pump_program = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
            
            account_keys = tx.get("transaction", {}).get("message", {}).get("accountKeys", [])
            program_ids = [k.get("pubkey") if isinstance(k, dict) else k for k in account_keys]
            
            if pump_program in program_ids:
                # This is a Pump.fun transaction - extract mint
                mint = await self._extract_mint_from_tx(tx)
                if mint:
                    await self._handle_copy_buy(mint, wallet_addr)
                    
        except Exception as e:
            logger.debug(f"Transaction analysis failed: {e}")
    
    async def _analyze_transaction(self, tx: dict, wallet_addr: str):
        """Analyze Helius-formatted transaction for Pump.fun buys."""
        try:
            # Helius provides parsed transaction type
            tx_type = tx.get("type", "")
            
            # Look for token transfers/swaps on Pump.fun
            if tx_type in ["SWAP", "TOKEN_MINT", "UNKNOWN"]:
                # Check program invocations
                instructions = tx.get("instructions", [])
                
                pump_program = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
                
                for ix in instructions:
                    if ix.get("programId") == pump_program:
                        # Extract the token mint from the transaction
                        token_transfers = tx.get("tokenTransfers", [])
                        for transfer in token_transfers:
                            mint = transfer.get("mint")
                            if mint and transfer.get("toUserAccount") == wallet_addr:
                                # This wallet received tokens = likely a buy
                                await self._handle_copy_buy(mint, wallet_addr)
                                return
                                
        except Exception as e:
            logger.debug(f"Helius tx analysis failed: {e}")
    
    async def _extract_mint_from_tx(self, tx: dict) -> Optional[str]:
        """Extract token mint address from a parsed transaction."""
        try:
            # Look through inner instructions for token program calls
            meta = tx.get("meta", {})
            post_token_balances = meta.get("postTokenBalances", [])
            
            for balance in post_token_balances:
                mint = balance.get("mint")
                if mint:
                    return mint
                    
            return None
        except:
            return None
    
    async def _handle_copy_buy(self, mint: str, source_wallet: str):
        """Handle a detected buy - validate and potentially copy."""
        try:
            # Avoid duplicate copies
            if mint in self.recent_copies:
                if time.time() - self.recent_copies[mint] < 300:  # 5 min cooldown
                    return
            
            wallet_name = self.wallet_names.get(source_wallet, source_wallet[:8])
            logger.info(f"🎯 COPY SIGNAL: {wallet_name} bought {mint[:12]}...")
            
            # Check daily limit
            if self.daily_copy_count >= self.max_daily_copies:
                logger.info(f"⚠️ Daily copy limit reached - skipping")
                return
            
            # Add delay before following (avoid front-running detection)
            await asyncio.sleep(self.copy_delay_seconds)
            
            # Validate through market sniper's vetting (if available)
            if self.market_sniper:
                # Use sniper's vetting logic
                should_snipe = await self.market_sniper._should_snipe_mint(mint)
                if not should_snipe:
                    logger.info(f"⚠️ Copy target failed vetting - skipping {mint[:12]}")
                    return
                
                # Execute the copy trade through sniper
                await self.market_sniper._execute_snipe(
                    mint=mint,
                    symbol=f"COPY-{wallet_name[:8]}",
                    mc=0,  # Will be fetched fresh
                    score=100,  # Copy trades get high priority
                    momentum=100,
                    buy_amount_override=self.copy_amount_sol
                )
            else:
                logger.warning("No market sniper attached - copy trade skipped")
                return
            
            # Track the copy
            self.recent_copies[mint] = time.time()
            self.daily_copy_count += 1
            
            logger.info(f"✅ COPY EXECUTED: Following {wallet_name} into {mint[:12]} ({self.daily_copy_count}/{self.max_daily_copies} today)")
            
        except Exception as e:
            logger.error(f"Copy buy handling failed: {e}")
    
    def stop(self):
        """Stop the copy trader."""
        self.running = False
        logger.info("Copy trader stopped")


# Singleton instance
_copy_trader_instance = None

def get_copy_trader(market_sniper=None):
    """Get singleton CopyTrader instance."""
    global _copy_trader_instance
    if _copy_trader_instance is None:
        _copy_trader_instance = CopyTrader(market_sniper)
    elif market_sniper and not _copy_trader_instance.market_sniper:
        _copy_trader_instance.market_sniper = market_sniper
    return _copy_trader_instance
