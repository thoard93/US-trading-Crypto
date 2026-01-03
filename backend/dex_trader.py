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
from solders.message import to_bytes_versioned

class DexTrader:
    def __init__(self, private_key=None):
        # Load wallet from environment or argument
        private_key = private_key or os.getenv('SOLANA_PRIVATE_KEY')
        self.rpc_url = os.getenv('SOLANA_RPC_URL', 'https://api.mainnet-beta.solana.com')
        
        if private_key:
            try:
                # Handle both base58 and byte array formats
                if private_key.startswith('['):
                    # Byte array format
                    key_bytes = bytes(eval(private_key))
                else:
                    # Base58 format
                    key_bytes = base58.b58decode(private_key)
                
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
        self.slippage_bps = 100  # 1% slippage
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
                return float(accounts[0]['account']['data']['parsed']['info']['tokenAmount']['uiAmount'] or 0)
            return 0
        except Exception as e:
            print(f"Error getting token balance: {e}")
            return 0
    
    def get_jupiter_quote(self, input_mint, output_mint, amount_lamports):
        """Get swap quote from Jupiter."""
        try:
            # url = "https://quote-api.jup.ag/v6/quote" # Failed DNS
            url = "https://public.jupiterapi.com/quote"
            params = {
                "inputMint": input_mint,
                "outputMint": output_mint,
                "amount": str(amount_lamports),
                "slippageBps": self.slippage_bps,
                "onlyDirectRoutes": "false"
            }
            response = requests.get(url, params=params)
            if response.status_code == 200:
                return response.json()
            else:
                print(f"Jupiter quote error: {response.text}")
                return None
        except Exception as e:
            print(f"Error getting Jupiter quote: {e}")
            return None
    
    def execute_swap(self, input_mint, output_mint, amount_lamports):
        """Execute a swap via Jupiter."""
        if not self.keypair:
            return {"error": "Wallet not initialized"}
        
        try:
            # 1. Get quote
            quote = self.get_jupiter_quote(input_mint, output_mint, amount_lamports)
            if not quote:
                return {"error": "Failed to get quote"}
            
            # 2. Get swap transaction
            # swap_url = "https://quote-api.jup.ag/v6/swap" # Failed DNS
            swap_url = "https://public.jupiterapi.com/swap" 
            swap_body = {
                "quoteResponse": quote,
                "userPublicKey": self.wallet_address,
                "wrapAndUnwrapSol": True,
                "dynamicComputeUnitLimit": True,
                "prioritizationFeeLamports": "auto"
            }
            
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
            
            # The transaction from Jupiter already has placeholder signatures
            # We need to sign the MESSAGE (not the whole tx) and replace the first signature
            
            # Get the message bytes for signing
            # Note: MessageV0 in older Solders uses bytes(), not .serialize()
            message = unsigned_tx.message
            try:
                # Try .serialize() first (newer Solders)
                message_bytes = message.serialize()
            except AttributeError:
                # Fall back to bytes() (older Solders)
                message_bytes = bytes(message)
            
            # Sign the serialized message
            signature = self.keypair.sign_message(message_bytes)
            
            # Create a new transaction with our signature
            # The first signature slot is always for the fee payer (our wallet)
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
                    {"encoding": "base64", "skipPreflight": False, "preflightCommitment": "confirmed"}
                ]
            })
            
            result = send_response.json()
            
            if 'error' in result:
                return {"error": result['error']['message']}
            
            tx_signature = result.get('result')
            print(f"✅ Swap executed! TX: {tx_signature}")
            
            return {
                "success": True,
                "signature": tx_signature,
                "input_amount": amount_lamports,
                "output_amount": quote.get('outAmount'),
                "price_impact": quote.get('priceImpactPct')
            }
            
        except Exception as e:
            print(f"❌ Swap execution error: {e}")
            return {"error": str(e)}
    
    def buy_token(self, token_mint, sol_amount=None):
        """Buy a token using SOL."""
        if sol_amount is None:
            sol_amount = self.max_trade_sol
        
        # Safety check
        balance = self.get_sol_balance()
        if balance < sol_amount + 0.01:  # Keep 0.01 SOL for fees
            return {"error": f"Insufficient SOL. Balance: {balance:.4f}"}
        
        amount_lamports = int(sol_amount * 1e9)
        
        result = self.execute_swap(self.SOL_MINT, token_mint, amount_lamports)
        
        if result.get('success'):
            # Track position
            self.positions[token_mint] = {
                "entry_sol": sol_amount,
                "tokens_received": int(result.get('output_amount', 0)),
                "tx": result.get('signature')
            }
        
        return result
    
    def sell_token(self, token_mint, percentage=100):
        """Sell token back to SOL."""
        token_balance = self.get_token_balance(token_mint)
        
        if token_balance <= 0:
            return {"error": "No tokens to sell"}
        
        # Calculate amount to sell
        sell_amount = int(token_balance * (percentage / 100) * 1e6)  # Assuming 6 decimals
        
        result = self.execute_swap(token_mint, self.SOL_MINT, sell_amount)
        
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
