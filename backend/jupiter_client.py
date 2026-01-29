"""
Jupiter Swap Client - Sells via Raydium/Jupiter after token graduation.
Phase 71: Implements Grok's recommendation for post-graduation exits.

When tokens hit ~$69k MC, they migrate from Pump.fun to Raydium.
This module handles selling via Jupiter aggregator for better liquidity.
"""
import asyncio
import logging
import os
import base64
import requests
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

# Jupiter API (v6)
JUPITER_QUOTE_API = "https://quote-api.jup.ag/v6/quote"
JUPITER_SWAP_API = "https://quote-api.jup.ag/v6/swap"

# SOL mint address (native)
SOL_MINT = "So11111111111111111111111111111111111111112"

# Default slippage for Jupiter swaps (in basis points)
DEFAULT_SLIPPAGE_BPS = int(os.getenv('JUPITER_SLIPPAGE_BPS', '300'))  # 3%


class JupiterClient:
    """
    Jupiter aggregator client for swapping tokens to SOL.
    Used as fallback when Pump.fun sells fail (token graduated to Raydium).
    """
    
    def __init__(self, wallet_pubkey: str = None):
        self.wallet_pubkey = wallet_pubkey
        self.session = requests.Session()
        self.session.headers.update({
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        })
    
    def get_quote(
        self,
        input_mint: str,
        amount: int,
        slippage_bps: int = DEFAULT_SLIPPAGE_BPS
    ) -> Optional[dict]:
        """
        Get a swap quote from Jupiter.
        
        Args:
            input_mint: Token mint to sell
            amount: Amount in token's smallest unit (lamports equivalent)
            slippage_bps: Slippage tolerance in basis points
            
        Returns:
            Quote response dict or None on failure
        """
        try:
            params = {
                "inputMint": input_mint,
                "outputMint": SOL_MINT,
                "amount": str(amount),
                "slippageBps": slippage_bps,
                "onlyDirectRoutes": "false",
                "asLegacyTransaction": "false"
            }
            
            logger.info(f"🔍 Getting Jupiter quote: {input_mint[:12]}... -> SOL ({amount:,} tokens)")
            
            resp = self.session.get(JUPITER_QUOTE_API, params=params, timeout=10)
            
            if resp.status_code != 200:
                logger.error(f"Jupiter quote failed: {resp.status_code} - {resp.text[:200]}")
                return None
            
            quote = resp.json()
            
            # Log quote details
            out_amount = int(quote.get('outAmount', 0))
            out_sol = out_amount / 1e9
            logger.info(f"📊 Jupiter quote: {out_sol:.6f} SOL output")
            
            return quote
            
        except Exception as e:
            logger.error(f"Jupiter quote error: {e}")
            return None
    
    def get_swap_transaction(
        self,
        quote_response: dict,
        wallet_pubkey: str = None
    ) -> Optional[str]:
        """
        Get serialized swap transaction from Jupiter.
        
        Args:
            quote_response: Quote from get_quote()
            wallet_pubkey: User's wallet public key
            
        Returns:
            Base64 encoded transaction or None
        """
        try:
            pubkey = wallet_pubkey or self.wallet_pubkey
            if not pubkey:
                logger.error("No wallet pubkey provided for Jupiter swap")
                return None
            
            payload = {
                "quoteResponse": quote_response,
                "userPublicKey": pubkey,
                "wrapAndUnwrapSol": True,
                "dynamicComputeUnitLimit": True,
                "prioritizationFeeLamports": "auto"
            }
            
            logger.info(f"🔄 Getting Jupiter swap transaction...")
            
            resp = self.session.post(JUPITER_SWAP_API, json=payload, timeout=15)
            
            if resp.status_code != 200:
                logger.error(f"Jupiter swap failed: {resp.status_code} - {resp.text[:200]}")
                return None
            
            data = resp.json()
            swap_tx = data.get('swapTransaction')
            
            if swap_tx:
                logger.info(f"✅ Got Jupiter swap transaction (base64 len: {len(swap_tx)})")
                return swap_tx
            else:
                logger.error(f"No swapTransaction in response: {data}")
                return None
                
        except Exception as e:
            logger.error(f"Jupiter swap tx error: {e}")
            return None
    
    async def execute_swap(
        self,
        input_mint: str,
        amount: int,
        trader,  # DexTrader instance for signing/sending
        slippage_bps: int = DEFAULT_SLIPPAGE_BPS
    ) -> Tuple[bool, Optional[str]]:
        """
        Execute full Jupiter swap: quote -> tx -> sign -> send.
        
        Args:
            input_mint: Token to sell
            amount: Amount in smallest units
            trader: DexTrader instance with signing capabilities
            slippage_bps: Slippage tolerance
            
        Returns:
            (success, tx_signature)
        """
        try:
            # 1. Get quote
            quote = self.get_quote(input_mint, amount, slippage_bps)
            if not quote:
                return False, None
            
            # 2. Get swap transaction
            wallet_pubkey = str(trader.wallet.pubkey())
            swap_tx_b64 = self.get_swap_transaction(quote, wallet_pubkey)
            if not swap_tx_b64:
                return False, None
            
            # 3. Decode and sign transaction
            from solders.transaction import VersionedTransaction
            
            tx_bytes = base64.b64decode(swap_tx_b64)
            tx = VersionedTransaction.from_bytes(tx_bytes)
            
            # Sign with wallet
            signed_tx = trader.wallet.sign_transaction(tx)
            
            # 4. Send via RPC (or Jito if available)
            logger.info("📤 Sending Jupiter swap transaction...")
            
            # Try Jito first for priority
            try:
                from jito_py_rpc.async_client import JitoRpcClient
                jito = JitoRpcClient()
                result = await jito.send_bundle([bytes(signed_tx)])
                if result:
                    logger.info(f"✅ Jupiter swap sent via Jito: {result}")
                    return True, str(result)
            except Exception as e:
                logger.debug(f"Jito Jupiter send failed, using RPC: {e}")
            
            # Fallback to regular RPC
            from solana.rpc.async_api import AsyncClient
            rpc_url = os.getenv('TRADING_RPC_URL', 'https://api.mainnet-beta.solana.com')
            
            async with AsyncClient(rpc_url) as client:
                result = await client.send_raw_transaction(
                    bytes(signed_tx),
                    opts={"skip_preflight": True, "max_retries": 3}
                )
                
                if result.value:
                    sig = str(result.value)
                    logger.info(f"✅ Jupiter swap sent: {sig}")
                    return True, sig
            
            return False, None
            
        except Exception as e:
            logger.error(f"Jupiter swap execution error: {e}")
            return False, None


# Check if a token has graduated to Raydium
async def check_token_graduated(mint: str, current_mc: float = None) -> bool:
    """
    Check if token has graduated from Pump.fun to Raydium.
    
    Graduation typically happens at ~$69k MC when bonding curve completes.
    """
    # Quick check based on MC
    if current_mc and current_mc > 65000:
        return True
    
    # Could also check via Pump.fun API or on-chain state
    # For now, use MC heuristic
    return False


# Singleton
_jupiter_client = None

def get_jupiter_client(wallet_pubkey: str = None) -> JupiterClient:
    """Get or create singleton Jupiter client."""
    global _jupiter_client
    if _jupiter_client is None:
        _jupiter_client = JupiterClient(wallet_pubkey)
    elif wallet_pubkey and not _jupiter_client.wallet_pubkey:
        _jupiter_client.wallet_pubkey = wallet_pubkey
    return _jupiter_client


# Test
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    client = JupiterClient("11111111111111111111111111111111")
    
    # Test quote (won't work without real token, but tests API connectivity)
    print("Testing Jupiter API connectivity...")
    quote = client.get_quote(
        "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",  # USDC
        1000000  # 1 USDC
    )
    if quote:
        print(f"Quote received: {quote.get('outAmount', 0) / 1e9:.6f} SOL")
    else:
        print("Quote failed (expected for test)")
