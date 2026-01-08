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
from solders.message import to_bytes_versioned
from nacl.signing import SigningKey

class DexTrader:
    def __init__(self, private_key=None):
        # Load wallet from environment or argument
        private_key = private_key or os.getenv('SOLANA_PRIVATE_KEY')
        if private_key: private_key = private_key.strip()

        # RPC Auto-Configuration
        env_rpc = os.getenv('SOLANA_RPC_URL')
        if env_rpc: env_rpc = env_rpc.strip()
        
        helius_key = os.getenv('HELIUS_API_KEY')
        if helius_key: helius_key = helius_key.strip()
        
        # Check if env_rpc is the slow public one
        is_slow_rpc = env_rpc and "api.mainnet-beta.solana.com" in env_rpc
        
        if helius_key and (not env_rpc or is_slow_rpc):
            print("🚀 Upgrading to High-Speed Helius RPC (Auto-detected key)")
            # If user had slow RPC set, we are overriding it
            if is_slow_rpc:
                print("⚠️ Overriding slow 'api.mainnet-beta' config with Helius!")
            self.rpc_url = f"https://mainnet.helius-rpc.com/?api-key={helius_key}"
        elif env_rpc:
            self.rpc_url = env_rpc
        else:
            print("⚠️ Using Slow Public RPC (High risk of slippage failure)")
            self.rpc_url = 'https://api.mainnet-beta.solana.com'
            
        print(f"DEBUG: Final RPC URL: {self.rpc_url}")
        print(f"DEBUG: Helius Key Present: {bool(helius_key)}")
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
    
    def get_jupiter_quote(self, input_mint, output_mint, amount_lamports, override_slippage=None):
        """Get swap quote from Jupiter."""
        try:
            slippage_bps = override_slippage if override_slippage else self.slippage_bps
            
            # Using public Jupiter API v6 - STANDARD ROUTING (Smart Router)
            # Reverted 'onlyDirectRoutes' and 'restrictIntermediateTokens' to let Jupiter find best path
            url = f"https://public.jupiterapi.com/quote?inputMint={input_mint}&outputMint={output_mint}&amount={amount_lamports}&slippageBps={slippage_bps}"
            
            response = requests.get(url)
            
            if response.status_code == 200:
                return response.json()
            else:
                print(f"Jupiter quote error: {response.text}")
                return None
        except Exception as e:
            print(f"Error getting Jupiter quote: {e}")
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
    
    def execute_swap(self, input_mint, output_mint, amount_lamports, override_slippage=None):
        """Execute a swap via Jupiter."""
        if not self.keypair:
            return {"error": "Wallet not initialized"}
        
        try:
            # Determine slippage for this trade
            slippage_bps = override_slippage if override_slippage else self.slippage_bps
            
            # 1. Get quote
            quote = self.get_jupiter_quote(input_mint, output_mint, amount_lamports, override_slippage)
            if not quote:
                return {"error": "Failed to get quote"}
            
            print(f"🔄 Jupiter Quote: slippage={slippage_bps}bps, outAmount={quote.get('outAmount')}")
            
            # 2. Get swap transaction
            swap_url = "https://public.jupiterapi.com/swap" 
            swap_body = {
                "quoteResponse": quote,
                "userPublicKey": self.wallet_address,
                "wrapAndUnwrapSol": True,
                "dynamicComputeUnitLimit": True,
                "prioritizationFeeLamports": 1000000,  # 0.001 SOL - Moderate Fast Fee (Worth $0.15 risk)
                # Disable dynamic slippage if we are providing a specific override (manual override takes precedence)
                # Enable Dynamic Slippage (let Jupiter manage volatility)
                "dynamicSlippage": True, 
                # Also specify max slippage BPS as fallback (Capped at 100% since API rejects > 10000)
                "autoSlippageCollisionUsdValue": 1000,
            }
            
            # Low Balance Fee Protection (Ensure we can SELL even if poor)
            try:
                 bal = self.get_sol_balance()
                 if bal < 0.005: 
                     # Cap fee to 50000 lamports (0.00005 SOL) to prevent failure
                     swap_body["prioritizationFeeLamports"] = 50000
                     print(f"⚠️ Critical Sol ({bal:.5f}). Capped Priority Fee.")
            except: pass
            
            swap_response = requests.post(swap_url, json=swap_body)
            if swap_response.status_code != 200:
                return {"error": f"Swap request failed: {swap_response.text}"}
            
            swap_data = swap_response.json()
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
            
            # 4. Send transaction
            signed_tx_bytes = bytes(signed_tx)
            signed_tx_base64 = base64.b64encode(signed_tx_bytes).decode('utf-8')
            
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
            
            if 'error' in result:
                msg = result['error']['message']
                if '0x177e' in str(msg):
                    msg += " (Slippage Tolerance Exceeded)"
                elif '0x1' in str(msg):
                    msg += " (Likely Insufficient SOL for Rent/Fees)"
                print(f"❌ Swap Failed: {msg}")
                return {"error": msg}
            
            tx_signature = result.get('result')
            print(f"📤 sentTransaction: {tx_signature}. Waiting for confirmation...")
            
            # Wait for confirmation (up to 60 seconds)
            import time
            confirmed = False
            for i in range(12):
                time.sleep(5)
                # Check status
                try:
                    status_resp = requests.post(self.rpc_url, json={
                         "jsonrpc": "2.0", "id": 1, "method": "getSignatureStatuses",
                         "params": [[tx_signature], {"searchTransactionHistory": True}]
                    })
                    status = status_resp.json().get('result', {}).get('value', [None])[0]
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
    
    def execute_pumpportal_swap(self, token_mint, action, amount_sol, slippage=25, priority_fee=0.02):
        """
        Execute a swap via PumpPortal API for pump.fun tokens.
        This has higher success rate than Jupiter for pump.fun tokens.
        """
        if not self.keypair:
            return {"error": "Wallet not initialized"}
        
        try:
            print(f"🎰 PumpPortal {action.upper()}: {token_mint[:16]}... | {amount_sol} SOL | Fee: {priority_fee}")
            
            # 1. Get transaction from PumpPortal
            response = requests.post(
                url="https://pumpportal.fun/api/trade-local",
                data={
                    "publicKey": self.wallet_address,
                    "action": action,  # "buy" or "sell"
                    "mint": token_mint,
                    "amount": amount_sol,
                    "denominatedInSol": "true",
                    "slippage": slippage,
                    "priorityFee": priority_fee,  # Dynamic Priority Fee
                    "pool": "auto",  # Auto-select pump or raydium
                    "skipPreflight": "false"  # Validate before sending
                },
                timeout=15
            )
            
            if response.status_code != 200:
                return {"error": f"PumpPortal API error: {response.text}"}
            
            # 2. Sign the transaction
            tx_bytes = response.content
            tx = VersionedTransaction.from_bytes(tx_bytes)
            message = tx.message
            
            # Sign using solders native method
            print("🔐 Signing PumpPortal transaction...")
            from nacl.signing import SigningKey
            
            # Get the seed (first 32 bytes) for signing
            seed = self._raw_secret[:32] if len(self._raw_secret) >= 32 else self._raw_secret
            signing_key = SigningKey(seed)
            
            message_bytes = bytes(message)
            signed = signing_key.sign(message_bytes)
            signature_bytes = signed.signature
            
            from solders.signature import Signature
            signature = Signature.from_bytes(signature_bytes)
            
            # Reconstruct signed transaction
            signed_tx = VersionedTransaction.populate(message, [signature])
            
            # 3. Send transaction via our RPC
            signed_tx_bytes = bytes(signed_tx)
            signed_tx_base64 = base64.b64encode(signed_tx_bytes).decode('utf-8')
            
            # Send with optimized params for landing
            send_response = requests.post(self.rpc_url, json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "sendTransaction",
                "params": [
                    signed_tx_base64,
                    {
                        "encoding": "base64", 
                        "skipPreflight": True,  # Skip local sim - PumpPortal already validated
                        "preflightCommitment": "confirmed",
                        "maxRetries": 5  # Increase retries for aggressive landing
                    }
                ]
            }, timeout=20)
            
            result = send_response.json()
            
            if 'error' in result:
                error_msg = result['error'].get('message', str(result['error']))
                print(f"❌ PumpPortal TX Failed: {error_msg}")
                return {"error": error_msg}
            
            tx_signature = result.get('result')
            print(f"📤 PumpPortal TX sent: {tx_signature}")
            
            # Wait for confirmation (up to 60 seconds)
            import time
            for i in range(12):
                time.sleep(5)
                confirm_response = requests.post(self.rpc_url, json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "getSignatureStatuses",
                    "params": [[tx_signature]]
                }, timeout=10)
                
                confirm_result = confirm_response.json()
                status = confirm_result.get('result', {}).get('value', [{}])[0]
                
                if status and status.get('confirmationStatus') in ['confirmed', 'finalized']:
                    if status.get('err'):
                        print(f"❌ PumpPortal TX FAILED on-chain: {status.get('err')}")
                        return {"error": f"TX failed on-chain: {status.get('err')}"}
                    print(f"✅ PumpPortal swap CONFIRMED! TX: {tx_signature}")
                    return {
                        "success": True,
                        "signature": tx_signature,
                        "provider": "pumpportal"
                    }
            
            print(f"⚠️ PumpPortal TX not confirmed after 30s: {tx_signature}")
            return {"error": "Transaction not confirmed", "signature": tx_signature}
            
        except Exception as e:
            print(f"❌ PumpPortal swap error: {e}")
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

        # UNIFIED JUPITER-ONLY FLOW (PumpPortal removed - was timing out and wasting 30s)
        # All tokens now use Jupiter with MAX SLIPPAGE (100%) and HIGH PRIORITY FEE
        if "pump" in token_mint.lower():
            print(f"💊 Pump.fun token detected. Using Jupiter DIRECT (PumpPortal bypass).")
        
        result = self.execute_swap(self.SOL_MINT, token_mint, amount_lamports, override_slippage=10000)
        
        # Retry logic if slippage exceeded
        if 'error' in result and ('0x177e' in str(result['error']) or '6014' in str(result['error'])):
            print("⚠️ Slippage exceeded. Retrying with 50% SLIPPAGE...")
            import time
            time.sleep(1)
            # Retry with 50% (gives more room than 15% default, but less likely to fail API than 100%)
            result = self.execute_swap(self.SOL_MINT, token_mint, amount_lamports, override_slippage=5000)
        
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
    
    def sell_token(self, token_mint, percentage=100):
        """Sell token back to SOL."""
        token_balance = self.get_token_balance(token_mint)
        
        if token_balance <= 0:
            return {"error": "No tokens to sell"}
        
        # Calculate amount to sell (Using RAW Integer - Decimals safe)
        if percentage == 100:
             sell_amount = token_balance
        else:
             sell_amount = int(token_balance * (percentage / 100))
        
        print(f"🔄 SELLING {token_mint} | Amount: {sell_amount}")

        result = self.execute_swap(token_mint, self.SOL_MINT, sell_amount)
        
        # Retry logic for Slippage (0x177e) on SELLS - Force Exit
        if 'error' in result and '0x177e' in str(result['error']):
             print("⚠️ Sell Slippage exceeded (15%). Retrying with 50% (Force Exit)...")
             result = self.execute_swap(token_mint, self.SOL_MINT, sell_amount, override_slippage=5000)
        
        # PUMPPORTAL FALLBACK for pump.fun tokens
        if 'error' in result and token_mint.lower().endswith('pump'):
            print("🎰 Jupiter sell failed on pump.fun token. Trying PumpPortal...")
            # For sells, we use percentage mode
            result = self.execute_pumpportal_swap(token_mint, "sell", "100%", slippage=50)
        
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
