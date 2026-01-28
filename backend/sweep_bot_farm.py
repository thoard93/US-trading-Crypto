import asyncio
import os
import logging
import base58
import time
from typing import List, Dict
from solders.keypair import Keypair
from solders.system_program import transfer, TransferParams
from solana.rpc.async_api import AsyncClient
from solders.transaction import Transaction
from solders.message import Message
from dotenv import load_dotenv

# Ensure .env is loaded
load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))

# Add parent dir to path for imports
import sys
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from wallet_manager import WalletManager
from dex_trader import DexTrader

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("CleanSlateSweep")

async def sell_all_tokens(trader: DexTrader, wallet_key: str):
    """Sells all SPL tokens in a wallet (Meme Factory tokens)."""
    label = trader.wallet_manager.get_wallet_label(wallet_key)
    addr = trader.wallet_manager.get_public_address(wallet_key)
    
    logger.info(f"🔍 [{label}] Scanning wallet {addr} for tokens...")
    
    # Temporarily switch trader to this wallet
    original_kp = trader.keypair
    original_addr = trader.wallet_address
    
    try:
        if not wallet_key:
            return
            
        try:
            trader.keypair = Keypair.from_base58_string(wallet_key)
            trader.wallet_address = str(trader.keypair.pubkey())
        except Exception as e:
            logger.error(f"  ❌ [{label}] Invalid private key: {e}")
            return
        
        holdings = trader.get_all_tokens()
        if not holdings:
            logger.info(f"  [{label}] No tokens found.")
            return

        for mint, amount in holdings.items():
            logger.info(f"  [{label}] Selling {amount} of {mint[:8]}...")
            # Use pump_sell for our created tokens
            result = trader.pump_sell(mint, token_amount_pct=100, payer_key=wallet_key)
            if result and result.get('success'):
                logger.info(f"  ✅ [{label}] Sold {mint[:8]}")
            else:
                logger.warning(f"  ⚠️ [{label}] Failed to sell {mint[:8]}: {result.get('error') if result else 'Unknown'}")
            
            # small delay between sells
            await asyncio.sleep(1)
            
    finally:
        # Restore original trader wallet
        trader.keypair = original_kp
        trader.wallet_address = original_addr

async def clean_slate_sweep():
    """
    1. Sells all tokens on Main + Support wallets.
    2. Waits for SOL to settle.
    3. Sweeps SOL from Support wallets to Main.
    4. PROTECTS Dylan/Secondary Main wallets from being swept.
    """
    manager = WalletManager()
    trader = DexTrader()
    
    primary_key = manager.get_main_key()
    if not primary_key:
        logger.error("❌ CRITICAL: SOLANA_PRIVATE_KEY not found in .env! Cannot sweep without a destination.")
        return
        
    primary_addr = manager.get_public_address(primary_key)
    
    # 1. IDENTIFY TARGETS
    support_keys = manager.get_all_support_keys()
    secondary_mains = manager.get_secondary_main_keys() # These are Dylan/Partner wallets
    
    if not support_keys and not secondary_mains:
        logger.warning("⚠️ No secondary or support wallets found! Check your .env file.")
    
    logger.info(f"🛡️ PROTECTION: Dylan/Partner wallets will NOT be swept: {[manager.get_public_address(k)[:8] for k in secondary_mains]}")
    logger.info(f"🎯 DESTINATION: Primary wallet {primary_addr[:8]}...")
    logger.info(f"📱 Found {len(support_keys)} support wallets to sweep.")

    # 2. SELL PHASE (Main + Supports)
    logger.info("\n=== PHASE 1: SELLING ALL TOKENS (CLEAN SLATE) ===")
    
    # Sell tokens on Primary wallet too!
    await sell_all_tokens(trader, primary_key)
    
    # Sell tokens on all Support wallets
    for key in support_keys:
        await sell_all_tokens(trader, key)
        
    logger.info("⏳ Waiting 60 seconds for SOL transactions to settle...")
    await asyncio.sleep(60)

    # 3. SWEEP PHASE (Supports Only)
    logger.info("\n=== PHASE 2: SWEEPING SOL FROM SUPPORTS TO MAIN ===")
    
    rpc_url = os.getenv('TRADING_RPC_URL') or os.getenv('HELIUS_API_KEY')
    if "helius" in rpc_url.lower() and not rpc_url.startswith("http"):
        rpc_url = f"https://mainnet.helius-rpc.com/?api-key={rpc_url}"
    
    client = AsyncClient(rpc_url or "https://api.mainnet-beta.solana.com")
    dest_pubkey = Keypair.from_base58_string(primary_key).pubkey()
    
    total_swept = 0
    for key in support_keys:
        try:
            kp = Keypair.from_base58_string(key)
            src_pubkey = kp.pubkey()
            label = manager.get_wallet_label(key)
            
            resp = await client.get_balance(src_pubkey)
            balance = resp.value
            
            # RENT EXEMPTION: We MUST leave enough SOL for the account to exist (~0.002 to 0.003 SOL)
            # If we sweep everything, we get UiTransactionError(InsufficientFundsForRent)
            rent_reserve = 3000000 # 0.003 SOL safe reserve
            fee = 10000 # 0.00001 SOL fee
            
            sweep_amount = balance - rent_reserve - fee
            
            if sweep_amount <= 0:
                logger.info(f"  [{label}] Balance too low to sweep (needs > 0.003 SOL). Found: {balance/1e9:.6f}")
                continue
                
            logger.info(f"  [{label}] Sweeping {sweep_amount/1e9:.6f} SOL (Leaving 0.003 for rent)...")
            
            recent_blockhash = (await client.get_latest_blockhash()).value.blockhash
            
            # Use solders-style transaction building for better compatibility
            instruction = transfer(TransferParams(
                from_pubkey=src_pubkey,
                to_pubkey=dest_pubkey,
                lamports=sweep_amount
            ))
            
            message = Message([instruction], src_pubkey)
            txn = Transaction([kp], message, recent_blockhash)
            
            send_resp = await client.send_raw_transaction(bytes(txn))
            logger.info(f"  ✅ Swept! TX: {send_resp.value[:12]}...")
            total_swept += sweep_amount
            
        except Exception as e:
            logger.error(f"  ❌ Sweep error for {manager.get_wallet_label(key)}: {e}")

    logger.info(f"\n🎉 CLEAN SLATE COMPLETE!")
    logger.info(f"💰 Total SOL Swept to Primary: {total_swept/1e9:.6f} SOL")
    
    # Correctly await the balance call
    final_resp = await client.get_balance(dest_pubkey)
    logger.info(f"🏠 Primary Wallet Balance: {final_resp.value/1e9:.6f} SOL")
    
    await client.close()

if __name__ == "__main__":
    asyncio.run(clean_slate_sweep())
