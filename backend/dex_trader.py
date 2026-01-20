"""
DEX Trader - Automated Solana token trading via Jupiter Aggregator.
Handles wallet management, swap execution, and position tracking.
"""
import os
import base64
import base58
import requests
from solders.keypair import Keypair
from solders.transaction import VersionedTransaction
from solders.signature import Signature
from solders.message import to_bytes_versioned, MessageV0
from solders.pubkey import Pubkey
from solders.instruction import Instruction, AccountMeta
from solders.system_program import transfer, TransferParams
from solders.address_lookup_table_account import AddressLookupTableAccount
from nacl.signing import SigningKey
import random
import time
from datetime import datetime

# Jito Block Engine Configuration (Multiple endpoints for failover)
JITO_BLOCK_ENGINES = [
    "https://mainnet.block-engine.jito.wtf",
    "https://ny.mainnet.block-engine.jito.wtf",
    "https://amsterdam.mainnet.block-engine.jito.wtf",
    "https://frankfurt.mainnet.block-engine.jito.wtf",
    "https://tokyo.mainnet.block-engine.jito.wtf",
]
JITO_TIP_FLOOR_URL = "https://bundles.jito.wtf/api/v1/bundles/tip_floor"
JITO_TIP_ACCOUNTS = [
    "96gYZGLnJYVFmbjzopPSU6QiEV5fGqZNyN9nmNhvrZU5",
    "HFqU5x63VTqvQss8hp11i4bVmLuSDZTRVyixBY22zQxD",
    "Cw8CFyM9FkoMi7K7Crf6HNQqf4uEMzpKw6QNghXLvLkY",
    "ADaUMid9yfUytqMBgopwjb2DTLSfertyPaXpK3hqT3dW",
    "DfXygSm4jCyNCybVYYK6DwvWqjKee8pbDmJGcLWNDXjh",
    "ADuUkR4vqLUMWXxW9gh6D6L8pMSawimctcNZ5pGwDcEt",
    "DttWaMuVvTiduZRnguLF7jNxTgiMBZ1hyAumKUiL2KRL",
    "3AVi9Tg9Uo68tJfuvoKvqKNWKkC5wPdSSdeBnizKZ6jT"
]

# Fallback Status RPCs (For confirmation checks when Helius is busy or out of credits)
# These are FREE public RPCs - lower rate limits but good for fallback
STATUS_FALLBACK_RPCS = [
    "https://api.mainnet-beta.solana.com",
    "https://rpc.ankr.com/solana",
    "https://solana.public-rpc.com",
]

# TRADING RPCs: Higher priority for sending transactions
# You can set TRADING_RPC_URL in .env to use a dedicated fast RPC for trades
# This reduces Helius usage (keep Helius for webhooks only)

class DexTrader:
    def __init__(self, private_key=None):
        # Load wallet from environment or argument
        private_key = private_key or os.getenv('SOLANA_PRIVATE_KEY')
        if private_key: private_key = private_key.strip()

        # RPC Auto-Configuration
        # Priority: TRADING_RPC_URL > SOLANA_RPC_URL > Auto-Helius > Public (slow)
        trading_rpc = os.getenv('TRADING_RPC_URL')  # Dedicated trading RPC (optional)
        if trading_rpc: trading_rpc = trading_rpc.strip()
        
        env_rpc = os.getenv('SOLANA_RPC_URL')
        if env_rpc: env_rpc = env_rpc.strip()
        
        helius_key = os.getenv('HELIUS_API_KEY')
        if helius_key: helius_key = helius_key.strip()
        
        # Check if env_rpc is the slow public one
        is_slow_rpc = env_rpc and "api.mainnet-beta.solana.com" in env_rpc
        
        # Use dedicated trading RPC if available (reduces Helius usage!)
        if trading_rpc:
            print("🚀 Using dedicated TRADING_RPC_URL for transactions (saves Helius credits)")
            self.rpc_url = trading_rpc
        elif helius_key and (not env_rpc or is_slow_rpc):
            print("🚀 Using Helius RPC for transactions")
            if is_slow_rpc:
                print("⚠️ Overriding slow 'api.mainnet-beta' config with Helius!")
            self.rpc_url = f"https://mainnet.helius-rpc.com/?api-key={helius_key}"
        elif env_rpc:
            self.rpc_url = env_rpc
        else:
            print("⚠️ Using Slow Public RPC (High risk of slippage failure)")
            self.rpc_url = 'https://api.mainnet-beta.solana.com'
            
        print(f"DEBUG: Trading RPC: {self.rpc_url[:50]}...")
        self._raw_secret = None  # Store raw secret for signing
        
        if private_key:
            try:
                # Handle both base58 and byte array formats
                if private_key.startswith('['):
                    # Byte array format
                    key_bytes = bytes(eval(private_key))
                else:
                    # Base58 format
                    key_bytes = base58.b58decode(private_key)
                
                # Store the raw bytes for signing (first 32 = seed, or all 64 if full key)
                self._raw_secret = key_bytes
                
                self.keypair = Keypair.from_bytes(key_bytes)
                self.wallet_address = str(self.keypair.pubkey())
                print(f"✅ DexTrader initialized. Wallet: {self.wallet_address[:8]}...{self.wallet_address[-4:]}")
            except Exception as e:
                print(f"❌ Failed to load wallet: {e}")
                self.keypair = None
                self.wallet_address = None
        else:
            print("⚠️ DexTrader: No SOLANA_PRIVATE_KEY found. DEX trading disabled.")
            self.keypair = None
            self.wallet_address = None
        
        # Token addresses
        self.SOL_MINT = "So11111111111111111111111111111111111111112"
        self.USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
        
        # Trading config
        self.slippage_bps = 3000  # 30% default for volatile markets (was 15%)
        self.max_trade_sol = 0.05  # Max 0.05 SOL per trade (~$6)
        
        # Active positions
        self.positions = {}
    
    def get_sol_balance(self):
        """Get SOL balance of wallet."""
        if not self.wallet_address:
            return 0
        
        try:
            response = requests.post(self.rpc_url, json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getBalance",
                "params": [self.wallet_address]
            })
            result = response.json()
            lamports = result.get('result', {}).get('value', 0)
            return lamports / 1e9  # Convert to SOL
        except Exception as e:
            print(f"Error getting balance: {e}")
            return 0
    
    def get_token_balance(self, token_mint):
        """Get SPL token balance."""
        if not self.wallet_address:
            return 0
        
        try:
            response = requests.post(self.rpc_url, json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getTokenAccountsByOwner",
                "params": [
                    self.wallet_address,
                    {"mint": token_mint},
                    {"encoding": "jsonParsed"}
                ]
            })
            result = response.json()
            accounts = result.get('result', {}).get('value', [])
            if accounts:
                # Return RAW integer amount (handled correctly regardless of decimals)
                return int(accounts[0]['account']['data']['parsed']['info']['tokenAmount']['amount'] or 0)
            return 0
        except Exception as e:
            print(f"Error getting token balance: {e}")
            return 0
    
    def get_jupiter_quote(self, input_mint, output_mint, amount_lamports, override_slippage=None, is_pump=False):
        """Get a quote from Jupiter Aggregator with retries and reliable fallbacks.
        Returns tuple: (quote_dict, timestamp) for freshness tracking.
        """
        try:
            # Determine slippage
            slippage_bps = override_slippage if override_slippage else self.slippage_bps
            
            import time
            # We try standard V6 first, then the reliable public proxy used in execute_swap
            hosts = [
                ("quote-api.jup.ag", "/v6/quote"),
                ("public.jupiterapi.com", "/quote")
            ]
            
            for host, path in hosts:
                for attempt in range(2):
                    try:
                        # For pump tokens, we strictly want direct routes to decrease latency if possibile
                        route_param = "&onlyDirectRoute=True" if is_pump else "&onlyDirectRoute=false"
                        url = f"https://{host}{path}?inputMint={input_mint}&outputMint={output_mint}&amount={amount_lamports}&slippageBps={slippage_bps}{route_param}"
                        response = requests.get(url, timeout=10)
                        if response.status_code == 200:
                            quote = response.json()
                            # Return quote with timestamp for freshness checking
                            quote['_timestamp'] = time.time()
                            return quote
                        else:
                            print(f"⚠️ Jupiter {host} Quote attempt {attempt+1} failed ({response.status_code})")
                    except Exception as e:
                        # Log DNS/Connection errors specifically for debugging
                        if "Errno -5" in str(e) or "Max retries exceeded" in str(e):
                            print(f"📡 DNS/Connection Error reaching {host} - trying next...")
                            break # Skip to next host immediately on DNS fail
                        print(f"⚠️ Jupiter {host} Quote attempt {attempt+1} error: {e}")
                    
                    if attempt < 1: time.sleep(1)
            
            return None
        except Exception as e:
            print(f"❌ Error in get_jupiter_quote: {e}")
            return None
    
    def get_all_tokens(self):
        """Fetch all SPL tokens held by the wallet."""
        if not self.keypair: return {}
        try:
            headers = {"Content-Type": "application/json"}
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getTokenAccountsByOwner",
                "params": [
                    str(self.wallet_address),
                    {"programId": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"},
                    {"encoding": "jsonParsed"}
                ]
            }
            resp = requests.post(self.rpc_url, json=payload, headers=headers, timeout=10)
            data = resp.json()
            
            holdings = {}
            if 'result' in data and 'value' in data['result']:
                for item in data['result']['value']:
                    info = item['account']['data']['parsed']['info']
                    mint = info['mint']
                    amount = float(info['tokenAmount']['uiAmount'])
                    
                    # Filter out tiny amounts and SOL wrappers if strictly meme trading
                    if amount > 0 and mint != self.SOL_MINT:
                        holdings[mint] = amount
            
            print(f"💰 Found {len(holdings)} existing tokens in wallet.")
            return holdings
        except Exception as e:
            print(f"❌ Error fetching wallet holdings: {e}")
            return {}
    
    def execute_swap(self, input_mint, output_mint, amount_lamports, override_slippage=None, use_jito=False, priority=False, is_pump=False):
        """Execute a swap via Jupiter with optional Jito bundle support."""
        if not self.keypair:
            return {"error": "Wallet not initialized"}
        
        try:
            # Determine slippage for this trade
            slippage_bps = override_slippage if override_slippage else self.slippage_bps
            
            # Dynamic Jito Tip Floor (LAMPS)
            jito_tip_lamports = 0
            if use_jito:
                jito_tip_lamports = self.get_jito_tip_amount_lamports()
                if priority:
                    # PRIORITY EXIT: 2x the normal tip to ensure we land first
                    jito_tip_lamports = int(jito_tip_lamports * 2.0)
                    print(f"⚡ PRIORITY TIP ENABLED: {jito_tip_lamports / 1e9:.6f} SOL")
            
            # 1. Get quote with freshness tracking
            quote = self.get_jupiter_quote(input_mint, output_mint, amount_lamports, override_slippage, is_pump=is_pump)
            if not quote:
                return {"error": "Failed to get quote"}
            
            # PHASE 44: Turbo-Quote Guard - Reject stale quotes
            # 0.5s for pump.fun (extreme volatility) | 1.0s for everything else
            staleness_threshold = 0.5 if is_pump else 1.0
            quote_age = time.time() - quote.get('_timestamp', 0)
            if quote_age > staleness_threshold:
                print(f"⚠️ Quote too stale ({quote_age:.1f}s old). Fetching fresh turbo quote...")
                quote = self.get_jupiter_quote(input_mint, output_mint, amount_lamports, override_slippage, is_pump=is_pump)
                if not quote:
                    return {"error": "Failed to get fresh quote"}
            
            print(f"🔄 {'[TURBO] ' if is_pump else ''}Jupiter Quote: slippage={slippage_bps}bps, outAmount={quote.get('outAmount')}, age={quote_age:.2f}s")

            
            # 2. Get swap transaction with retries and fallback
            swap_data = None
            hosts = [
                ("quote-api.jup.ag", "/v6/swap"),
                ("jupiter-quote-api.jup.ag", "/v6/swap"),
                ("public.jupiterapi.com", "/swap")
            ]
            
            # Low Balance Fee Protection (Ensure we can SELL even if poor)
            initial_fee = "auto"
            try:
                 bal = self.get_sol_balance()
                 if bal < 0.005: 
                     initial_fee = 50000
                     print(f"⚠️ Critical Sol ({bal:.5f}). Capped Priority Fee.")
            except: pass

            for host, path in hosts:
                swap_url = f"https://{host}{path}"
                swap_body = {
                    "quoteResponse": quote,
                    "userPublicKey": self.wallet_address,
                    "wrapAndUnwrapSol": True,
                    "dynamicComputeUnitLimit": True,
                    "prioritizationFeeLamports": initial_fee if not use_jito else None, 
                    "jitoTipLamports": jito_tip_lamports if use_jito else None,
                    # Disable dynamicSlippage for pump.fun or high-conviction 100% swaps to force execution
                    "dynamicSlippage": False if (is_pump or (override_slippage and override_slippage >= 10000)) else True, 
                }
                
                # For high slippage or pump retries, enforce direct route to minimize hops
                if is_pump or (override_slippage and override_slippage >= 9000):
                    swap_body["onlyDirectRoute"] = True
                
                success = False
                for attempt in range(2):
                    try:
                        swap_response = requests.post(swap_url, json=swap_body, timeout=15)
                        if swap_response.status_code == 200:
                            swap_data = swap_response.json()
                            success = True
                            break
                        else:
                            print(f"⚠️ Jupiter {host} Swap attempt {attempt+1} failed ({swap_response.status_code})")
                    except Exception as e:
                        if "Errno -5" in str(e) or "Max retries exceeded" in str(e):
                            print(f"📡 DNS/Connection Error reaching {host} - trying next...")
                            break
                        print(f"⚠️ Jupiter {host} Swap attempt {attempt+1} error: {e}")
                    
                    if attempt < 1: time.sleep(1)
                
                if success: break
            
            if not swap_data:
                return {"error": "Failed to get swap transaction after trying multiple hosts"}
            swap_tx_base64 = swap_data.get('swapTransaction')
            
            if not swap_tx_base64:
                return {"error": "No swap transaction returned"}
            
            # 3. Deserialize, sign, and send transaction
            tx_bytes = base64.b64decode(swap_tx_base64)
            
            # Parse the transaction from Jupiter
            unsigned_tx = VersionedTransaction.from_bytes(tx_bytes)
            
            # Get the message bytes using the CORRECT method for versioned transactions
            message = unsigned_tx.message
            message_bytes = to_bytes_versioned(message)
            
            # Try Solders native signing first (most reliable if available)
            try:
                signature = self.keypair.sign_message(message_bytes)
                print(f"🔐 Signed using Solders native method")
            except Exception as e:
                print(f"⚠️ Solders sign failed ({e}), using nacl fallback")
                # Fallback to nacl signing
                if self._raw_secret and len(self._raw_secret) >= 32:
                    signing_key = SigningKey(self._raw_secret[:32])
                else:
                    secret_key_bytes = bytes(self.keypair)
                    signing_key = SigningKey(secret_key_bytes[:32])
                
                signed_message = signing_key.sign(message_bytes)
                signature = Signature.from_bytes(signed_message.signature)
            
            # Debug info
            print(f"🔐 Signing with wallet: {self.wallet_address}")
            print(f"🔐 Message size: {len(message_bytes)} bytes")
            
            # Reconstruct transaction with our signature
            signed_tx = VersionedTransaction.populate(message, [signature])
            
            # 4. PHASE 43: Pre-flight Simulation (Catch failures for FREE before on-chain)
            signed_tx_bytes = bytes(signed_tx)
            signed_tx_base64 = base64.b64encode(signed_tx_bytes).decode('utf-8')
            
            # Simulate transaction before sending (costs nothing, catches ~80% of slippage failures)
            try:
                sim_response = requests.post(self.rpc_url, json={
                    "jsonrpc": "2.0", "id": 1,
                    "method": "simulateTransaction",
                    # PHASE 43.1: Use 'confirmed' commitment for more reliable simulation
                    "params": [signed_tx_base64, {"encoding": "base64", "commitment": "confirmed"}]
                }, timeout=10)

                sim_result = sim_response.json()
                sim_err = sim_result.get('result', {}).get('err')
                
                if sim_err:
                    err_str = str(sim_err)
                    # Check for slippage error (6014 / 0x177e)
                    if '6014' in err_str or '0x177e' in err_str:
                        print(f"🛑 PRE-FLIGHT ABORT: Slippage would fail (saved TX fee!)")
                        return {"error": "Pre-flight simulation: Slippage exceeded", "simulated": True}
                    else:
                        print(f"🛑 PRE-FLIGHT ABORT: Simulation failed: {sim_err}")
                        return {"error": f"Pre-flight simulation failed: {sim_err}", "simulated": True}
                else:
                    print(f"✅ Pre-flight simulation PASSED (safe to submit)")
            except Exception as sim_e:
                # Don't block on simulation failure - proceed with caution
                print(f"⚠️ Pre-flight simulation error (proceeding anyway): {sim_e}")

            
            if use_jito:
                # Submit to ALL Jito Block Engines with Burst Resubmission
                tx_payload = {
                    "jsonrpc": "2.0", "id": 1,
                    "method": "sendTransaction",
                    "params": [signed_tx_base64, {"encoding": "base64"}]
                }
                
                print(f"🔐 Submitting Jito Bundle (Tip: {jito_tip_lamports / 1e9:.6f} SOL / {jito_tip_lamports:,} lamps)")
                
                # Burst resubmission for 15 seconds
                # Simultaneous fallback to standard RPC after first burst
                for attempt in range(5):
                    success_current_attempt = False
                    for jito_base in JITO_BLOCK_ENGINES:
                        try:
                            jito_url = f"{jito_base}/api/v1/transactions?bundleOnly=true"
                            resp = requests.post(jito_url, json=tx_payload, timeout=5)
                            if resp.status_code == 200:
                                result = resp.json()
                                cur_sig = result.get('result')
                                if cur_sig:
                                    tx_signature = cur_sig
                                    success_current_attempt = True
                                else:
                                    err_msg = result.get('error', {}).get('message', 'Unknown Error')
                                    # Silencing 'already processed' as it means success or propagation
                                    if "already processed" not in err_msg.lower():
                                        print(f"📋 DEBUG: Jito {jito_base.split('.')[1]} Error: {err_msg}")
                            else:
                                if resp.status_code != 400: # Silence 400s as they are usually 'already processed'
                                    print(f"📋 DEBUG: Jito {jito_base.split('.')[1]} HTTP {resp.status_code}: {resp.text}")
                        except: continue
                    
                    # DUAL SUBMISSION FALLBACK: Also send to standard RPC after second attempt
                    # This ensures that even if Jito is dropping it, a standard leader might catch it
                    if attempt >= 1:
                        try:
                            print(f"📡 Sending standard RPC fallback (Attempt {attempt})...")
                            requests.post(self.rpc_url, json={
                                "jsonrpc": "2.0", "id": 1, "method": "sendTransaction",
                                "params": [signed_tx_base64, {"encoding": "base64", "skipPreflight": True}]
                            }, timeout=5)
                        except Exception as e:
                            print(f"⚠️ Fallback RPC send failed: {e}")

                    if attempt == 0 and not success_current_attempt:
                        # If Jito failed initially, don't alert, try the standard RPC as a direct fallback
                        try:
                            print(f"📡 Jito initial fail. Attempting direct RPC fallback...")
                            fallback_resp = requests.post(self.rpc_url, json={
                                "jsonrpc": "2.0", "id": 1, "method": "sendTransaction",
                                "params": [signed_tx_base64, {"encoding": "base64", "skipPreflight": True}]
                            }, timeout=5)
                            res = fallback_resp.json()
                            if res.get('result'):
                                tx_signature = res.get('result')
                                success_current_attempt = True
                                print(f"🚀 Jito initial fail. Direct fallback success: {tx_signature}")
                            else:
                                print(f"❌ Direct RPC fallback failed: {res}")
                        except Exception as e:
                            print(f"⚠️ Direct RPC fallback error: {e}")
                    
                    if attempt == 0 and not success_current_attempt:
                        return {"error": "Failed initial submission to all Jito Block Engines and RPC"}
                    
                    if attempt == 0:
                        print(f"📤 sentTransaction: {tx_signature}. Starting burst resubmission...")
                    
                    if attempt < 4: time.sleep(3) 
                
                print(f"✅ Burst complete. Waiting for confirmation: {tx_signature}")
            else:
                # Standard Helius Send
                print(f"📡 Sending standard transaction to Helius RPC...")
                send_response = requests.post(self.rpc_url, json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "sendTransaction",
                    "params": [
                        signed_tx_base64,
                        {"encoding": "base64", "skipPreflight": True, "preflightCommitment": "confirmed", "maxRetries": 5}
                    ]
                }, timeout=15)
                
                result = send_response.json()
                
                # DEBUG: Full RPC response
                print(f"📋 DEBUG: RPC sendTransaction response: {result}")
                
                if 'error' in result:
                    msg = result['error'].get('message', str(result['error']))
                    code = result['error'].get('code', 'unknown')
                    print(f"❌ Swap Failed [code={code}]: {msg}")
                    if '0x177e' in str(msg) or '6014' in str(msg) or '6001' in str(msg):
                        msg += " (Slippage Tolerance Exceeded)"
                    elif '0x1' in str(msg):
                        msg += " (Likely Insufficient SOL for Rent/Fees)"
                    return {"error": msg}
                
                tx_signature = result.get('result')
                print(f"📤 sentTransaction: {tx_signature}. Waiting for confirmation...")

            
            # Wait for confirmation (up to 60 seconds)
            confirmed = False
            print(f"⏳ Monitoring confirmation status for TX: {tx_signature}")
            for i in range(30): # 30 * 2s = 60s
                if i % 3 == 0: print(f"⏳ Confirmation check {i+1}/30...")
                time.sleep(2)

                # Check status across multiple RPCs for redundancy
                try:
                    status = None
                    status_sources = [self.rpc_url] + STATUS_FALLBACK_RPCS
                    
                    for rpc_url in status_sources:
                        try:
                            status_resp = requests.post(rpc_url, json={
                                 "jsonrpc": "2.0", "id": 1, "method": "getSignatureStatuses",
                                 "params": [[tx_signature], {"searchTransactionHistory": True}]
                            }, timeout=5)
                            
                            if status_resp.status_code == 200:
                                status_val = status_resp.json().get('result', {}).get('value', [None])[0]
                                if status_val:
                                    status = status_val
                                    src = rpc_url.split('.')[1] if '.' in rpc_url else 'Helius'
                                    conf = status.get('confirmationStatus', 'unknown')
                                    err = status.get('err')
                                    print(f"🏷️ Status [{src}]: {conf} | Err: {err}")
                                    break 
                        except:
                            continue # Try next RPC
                    
                    if status:
                        if status.get('err'):
                             print(f"❌ Transaction FAILED on-chain: {status['err']}")
                             return {"error": f"On-chain failure: {status['err']}"}
                        
                        if status.get('confirmationStatus') in ['confirmed', 'finalized']:
                             print(f"✅ Swap CONFIRMED! TX: {tx_signature}")
                             # Check actual balance change or assume success
                             return {
                                "success": True,
                                "signature": tx_signature,
                                "input_amount": amount_lamports,
                                "output_amount": quote.get('outAmount'),
                                "price_impact": quote.get('priceImpactPct')
                            }
                except Exception as e:
                    print(f"⚠️ Error checking status: {e}")
            
            print(f"⚠️ Jupiter TX not confirmed after 60s: {tx_signature}")
            return {"error": "Transaction detection timeout", "signature": tx_signature}
            
        except Exception as e:
            print(f"❌ Swap execution error: {e}")
            return {"error": str(e)}
    
    def get_jito_tip_amount_lamports(self):
        """Fetch dynamic tip amount from Jito API (returned in lamports)."""
        try:
            response = requests.get(JITO_TIP_FLOOR_URL, timeout=5)
            if response.status_code == 200:
                data = response.json()
                if data and len(data) > 0:
                    # Use 99th percentile for MAXIMUM priority (last attempt for pump.fun)
                    tip_sol = data[0].get('landed_tips_99th_percentile', 0.005)
                    # ULTRA MODE: Minimum 0.005 SOL (~$1) for pump.fun priority
                    # Max 0.02 SOL to cap costs
                    tip_sol = max(0.005, min(0.02, tip_sol))
                    return int(tip_sol * 1e9)
        except Exception as e:
            print(f"⚠️ Failed to fetch Jito tip floor: {e}")
        return 5000000  # Default fallback: 0.005 SOL (5M lamports) - ULTRA MODE
    
    def execute_jito_bundle(self, token_mint, sol_amount):
        """
        Execute swap via Jito for MEV protection and atomic execution.
        Uses Jupiter's /swap-instructions to build a SINGLE transaction with an internal tip.
        """
        if not self.keypair:
            return {"error": "Wallet not initialized"}
        
        try:
            import time
            from solders.hash import Hash
            
            amount_lamports = int(sol_amount * 1e9)
            
            # 1. Get dynamic tip amount
            tip_sol = self.get_jito_tip_amount()
            tip_lamports = int(tip_sol * 1e9)
            tip_account = Pubkey.from_string(random.choice(JITO_TIP_ACCOUNTS))
            
            # 2. Get Jupiter quote
            quote = self.get_jupiter_quote(self.SOL_MINT, token_mint, amount_lamports, override_slippage=10000)
            if not quote:
                return {"error": "Failed to get Jupiter quote"}
            
            # 3. Get swap instructions from Jupiter
            # Try multiple hosts and add retries to handle DNS/connection issues on Render
            instr_data = None
            hosts = [
                ("quote-api.jup.ag", "/v6/swap-instructions"),
                ("public.jupiterapi.com", "/swap-instructions")  # Base path (no /v6) for public mirror
            ]
            
            for host, path in hosts:
                instr_url = f"https://{host}{path}"
                instr_body = {
                    "quoteResponse": quote,
                    "userPublicKey": self.wallet_address,
                    "wrapAndUnwrapSol": True,
                }
                
                success = False
                for attempt in range(2):
                    try:
                        instr_response = requests.post(instr_url, json=instr_body, timeout=10)
                        if instr_response.status_code == 200:
                            instr_data = instr_response.json()
                            success = True
                            break
                        else:
                            print(f"⚠️ Jupiter {host} returned {instr_response.status_code} for swap-instructions")
                    except Exception as e:
                        if "Errno -5" in str(e) or "Max retries exceeded" in str(e):
                            print(f"📡 DNS/Connection Error reaching {host} (swap-instructions) - trying next...")
                            break 
                        print(f"⚠️ Jupiter {host} attempt {attempt+1} failed: {e}")
                    time.sleep(1)
                
                if success: break
            
            if not instr_data:
                return {"error": "Failed to fetch Jupiter swap instructions after trying all mirrors."}
            
            # 4. Helper to parse Jupiter instructions
            def parse_instr(obj):
                if not obj: return None
                return Instruction(
                    program_id=Pubkey.from_string(obj['programId']),
                    accounts=[AccountMeta(
                        pubkey=Pubkey.from_string(a['pubkey']),
                        is_signer=a['isSigner'],
                        is_writable=a['isWritable']
                    ) for a in obj['accounts']],
                    data=base64.b64decode(obj['data'])
                )

            instructions = []
            # Setup instructions
            for obj in instr_data.get('setupInstructions', []):
                instructions.append(parse_instr(obj))
            # Core swap instruction
            instructions.append(parse_instr(instr_data.get('swapInstruction')))
            # Cleanup instruction
            if instr_data.get('cleanupInstruction'):
                instructions.append(parse_instr(instr_data.get('cleanupInstruction')))
            
            # 5. Add Jito Tip instruction (SOL transfer)
            # Use solders.system_program.transfer (already imported as transfer)
            tip_ix = transfer(TransferParams(
                from_pubkey=self.keypair.pubkey(),
                to_pubkey=tip_account,
                lamports=tip_lamports
            ))
            instructions.append(tip_ix)
            
            # 6. Fetch Address Lookup Table accounts
            alt_addresses = instr_data.get('addressLookupTableAddresses', [])
            lookup_tables = []
            if alt_addresses:
                rpc_payload = {
                    "jsonrpc": "2.0", "id": 1,
                    "method": "getMultipleAccounts",
                    "params": [alt_addresses, {"encoding": "base64"}]
                }
                rpc_response = requests.post(self.rpc_url, json=rpc_payload, timeout=15).json()
                accounts_data = rpc_response.get('result', {}).get('value', [])
                
                for i, acc_data in enumerate(accounts_data):
                    if acc_data and acc_data.get('data'):
                        alt_pubkey = Pubkey.from_string(alt_addresses[i])
                        # Decode base64 data
                        raw_data = base64.b64decode(acc_data['data'][0])
                        
                        # PARSE ALT DATA: Skip 56-byte header, then 32 bytes per address
                        # Header: 4(type)+8(deactiv)+8(last_ext)+1(index)+1(has_auth)+32(auth)+2(padding?) = 56
                        addresses = []
                        for j in range(56, len(raw_data), 32):
                            addr_bytes = raw_data[j:j+32]
                            if len(addr_bytes) == 32:
                                addresses.append(Pubkey.from_bytes(addr_bytes))
                        
                        if addresses:
                            lookup_tables.append(AddressLookupTableAccount(alt_pubkey, addresses))
                            print(f"✅ Loaded ALT {alt_pubkey[:8]} with {len(addresses)} addresses")

            # 7. Get fresh blockhash
            blockhash_resp = requests.post(self.rpc_url, json={
                "jsonrpc": "2.0", "id": 1,
                "method": "getLatestBlockhash",
                "params": [{"commitment": "confirmed"}]
            }, timeout=10).json()
            recent_blockhash = Hash.from_string(blockhash_resp['result']['value']['blockhash'])
            
            # 8. Compile MessageV0
            message = MessageV0.compile(
                payer=self.keypair.pubkey(),
                instructions=instructions,
                address_lookup_table_accounts=lookup_tables,
                recent_blockhash=recent_blockhash
            )
            
            # 9. Sign and build VersionedTransaction
            message_bytes = to_bytes_versioned(message)
            signature = self.keypair.sign_message(message_bytes)
            signed_tx = VersionedTransaction.populate(message, [signature])
            signed_tx_b64 = base64.b64encode(bytes(signed_tx)).decode('utf-8')
            
            # 10. Submit to Jito
            tx_payload = {
                "jsonrpc": "2.0", "id": 1,
                "method": "sendTransaction",
                "params": [signed_tx_b64, {"encoding": "base64"}]
            }
            
            print(f"🔐 Built Jito TX with internal tip: {tip_sol:.6f} SOL")
            print(f"📤 Submitting to Jito (bundleOnly=true)...")
            
            tx_signature = None
            for jito_base in JITO_BLOCK_ENGINES:
                jito_url = f"{jito_base}/api/v1/transactions?bundleOnly=true"
                try:
                    response = requests.post(jito_url, json=tx_payload, timeout=10)
                    result = response.json()
                    
                    if 'error' in result:
                        error_msg = str(result['error'].get('message', result['error']))
                        if 'rate' in error_msg.lower() or 'congested' in error_msg.lower():
                            print(f"⚠️ {jito_base.split('//')[1].split('.')[0]} rate limited...")
                            continue
                        print(f"❌ Jito error from {jito_base.split('//')[1].split('.')[0]}: {error_msg}")
                        continue
                    
                    tx_signature = result.get('result')
                    print(f"✅ Jito TX submitted via {jito_base.split('//')[1].split('.')[0]}!")
                    print(f"   Signature: {tx_signature}")
                    break
                except Exception: continue
            
            if not tx_signature:
                return {"error": "All Jito endpoints rate-limited or unavailable"}
            
            # 11. Wait for confirmation
            for i in range(12):
                time.sleep(2.5)
                try:
                    status_resp = requests.post(self.rpc_url, json={
                        "jsonrpc": "2.0", "id": 1,
                        "method": "getSignatureStatuses",
                        "params": [[tx_signature], {"searchTransactionHistory": True}]
                    }, timeout=10).json()
                    status = status_resp.get('result', {}).get('value', [None])[0]
                    
                    if status:
                        if status.get('err'):
                            print(f"⚡ Jito TX REVERTED: {status['err']}")
                            return {"error": f"TX reverted (no fee): {status['err']}"}
                        if status.get('confirmationStatus') in ['confirmed', 'finalized']:
                            print(f"🎉 JITO TX CONFIRMED! Status: {status['confirmationStatus']}")
                            return {
                                "success": True,
                                "signature": tx_signature,
                                "provider": "jito",
                                "output_amount": quote.get('outAmount')
                            }
                except Exception: pass
            
            print(f"⚠️ Jito TX not confirmed after 30s: {tx_signature}")
            return {"error": "Transaction confirmation timeout", "signature": tx_signature}
            
        except Exception as e:
            print(f"❌ Jito V4 error: {e}")
            import traceback
            traceback.print_exc()
            return {"error": str(e)}
    
    def buy_token(self, token_mint, sol_amount=None):
        """Buy a token using SOL."""
        if sol_amount is None:
            sol_amount = self.max_trade_sol
        
        # Prevent buying SOL/USDC wrappers
        if token_mint in [self.SOL_MINT, self.USDC_MINT]:
            return {"error": "Cannot buy SOL/USDC native wrappers"}

        # Safety check & Dynamic Sizing
        balance = self.get_sol_balance()
        required = sol_amount + 0.07 # Buffer increased to 0.07 SOL (~$10)
        
        if balance < required:
            if balance > 0.08: # Stricter Safety Floor
                # Increase buffer to leave at least 0.07 for fees/rent
                safe_amount = balance - 0.07 
                if safe_amount < 0.01:
                    return {"error": f"Insufficient SOL for safe trade. Balance: {balance:.4f}"}
                    
                print(f"⚠️ Low balance ({balance:.4f} SOL). Reducing buy size from {sol_amount} to {safe_amount:.4f} SOL")
                sol_amount = safe_amount
            else:
                return {"error": f"Insufficient SOL guardrail. Balance: {balance:.4f} < 0.08"}
        
        amount_lamports = int(sol_amount * 1e9)
        
        user_id = getattr(self, 'user_id', 'Unknown')
        print(f"🔄 BUYING (User {user_id}) {token_mint} | SOL: {sol_amount:.4f}")
        print(f"DEBUG: SOL Balance: {balance:.6f}, Required: {required:.6f}")

        is_pump = "pump" in token_mint.lower()
        if is_pump:
            print(f"🎰 Pump.fun token detected. Routing via JUPITER + JITO (100% slippage, Turbo-Quote, Direct).")
        else:
            print(f"🚀 Routing via JUPITER + JITO (atomic execution).")
        
        # BEAST MODE 2.0: Multi-Retry loop for maximum landing rate
        # 3 attempts total for pump.fun tokens
        max_attempts = 3 if is_pump else 1
        result = {"error": "No attempts made"}
        
        for attempt in range(max_attempts):
            if attempt > 0:
                print(f"⚡ BEAST MODE Retry {attempt}/{max_attempts-1} for {token_mint[:8]}...")
                time.sleep(0.3) # Fast jitter to catch next block
                
            result = self.execute_swap(
                self.SOL_MINT, 
                token_mint, 
                amount_lamports, 
                override_slippage=10000, 
                use_jito=True,
                is_pump=is_pump
            )
            
            if result.get('success'):
                break
            
            # If error is not slippage/volatility related, don't waste retries (e.g. insufficient funds)
            if not any(err in str(result.get('error', '')) for err in ['0x177e', '6014', '6001', '0x1']):
                break
        
        if 'error' in result:
             print(f"🛑 Entry failed after {max_attempts} attempts. Error: {result['error'][:50]}")

        
        if result.get('success'):
            # Track position
            self.positions[token_mint] = {
                "entry_sol": sol_amount,
                "tokens_received": int(result.get('output_amount', 0)),
                "tx": result.get('signature')
            }
            # REFRESH HOLDINGS IMMEDIATELY for fast-fail selling
            print("🔄 Refreshing wallet holdings after buy...")
            self.get_all_tokens()
        
        return result
    
    def sell_token(self, token_mint, percentage=100, override_slippage=None, priority=False):
        """Sell token back to SOL.
        
        Args:
            token_mint: Token address to sell
            percentage: Percentage of holdings to sell (default 100%)
            override_slippage: Optional custom slippage in BPS (for retry queue)
            priority: If True, use higher Jito tip for fast exit
        """
        token_balance = self.get_token_balance(token_mint)
        
        if token_balance <= 0:
            return {"error": "No tokens to sell"}
        
        # Calculate amount to sell (Using RAW Integer - Decimals safe)
        if percentage == 100:
             sell_amount = token_balance
        else:
             sell_amount = int(token_balance * (percentage / 100))
        
        # Use provided slippage or default to 100% for meme coin exits
        slippage = override_slippage if override_slippage else 10000
        
        print(f"🔄 SELLING {token_mint} | Amount: {sell_amount} | Pct: {percentage}% | Slippage: {slippage // 100}% | Priority: {priority}")
        print(f"DEBUG: Wallet: {self.wallet_address}")


        # Determine if it's a pump token for prioritized routing
        is_pump = "pump" in token_mint.lower()

        # Aggressive Sell: Use provided slippage + Jito for atomic exit (no fee on fail)
        result = self.execute_swap(
            token_mint, 
            self.SOL_MINT, 
            sell_amount, 
            override_slippage=slippage, 
            use_jito=True, 
            priority=priority,
            is_pump=is_pump
        )
        
        if result.get('success') and percentage == 100:
            # Remove from positions
            if token_mint in self.positions:
                del self.positions[token_mint]
        
        return result


# Test function
if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    
    trader = DexTrader()
    print(f"SOL Balance: {trader.get_sol_balance():.4f}")
