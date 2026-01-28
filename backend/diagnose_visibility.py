import os
import requests
import base58
from dotenv import load_dotenv

# Ensure .env is loaded from the backend directory
load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))

def get_balance(rpc_url, address):
    try:
        resp = requests.post(rpc_url, json={
            "jsonrpc": "2.0", "id": 1,
            "method": "getBalance", "params": [address]
        }, timeout=10).json()
        lamports = resp.get('result', {}).get('value', 0)
        return lamports / 1e9
    except: return 0

def list_tokens(rpc_url, address):
    programs = {
        "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA": "Standard SPL",
        "TokenzQdBNb9W18K1itX94TfC6jV09z9V696VR": "Token-2022"
    }
    
    all_tokens = []
    for pid, name in programs.items():
        try:
            resp = requests.post(rpc_url, json={
                "jsonrpc": "2.0", "id": 1,
                "method": "getTokenAccountsByOwner",
                "params": [address, {"programId": pid}, {"encoding": "jsonParsed"}]
            }, timeout=10).json()
            
            accounts = resp.get('result', {}).get('value', [])
            for acc in accounts:
                info = acc['account']['data']['parsed']['info']
                mint = info['mint']
                amount = float(info['tokenAmount']['uiAmount'] or 0)
                if amount > 0:
                    all_tokens.append({"mint": mint, "amount": amount, "type": name})
        except Exception as e:
            print(f"  ❌ Error checking {name}: {e}")
            
    return all_tokens

def main():
    rpc_url = "https://powerful-warmhearted-wish.solana-mainnet.quiknode.pro/4627a4da7f076c17804afd75d9966b0afe78fa23/"
    print(f"🌐 Using RPC: {rpc_url[:50]}...")
    
    # Load keys
    primary = os.getenv('SOLANA_PRIVATE_KEY')
    supports = [k.strip() for k in os.getenv('SOLANA_SUPPORT_KEYS', '').split(',') if k.strip()]
    dylan = [k.strip() for k in os.getenv('SOLANA_MAIN_KEYS', '').split(',') if k.strip()]
    
    wallets = []
    if primary: wallets.append(("Primary", primary))
    for idx, k in enumerate(supports): wallets.append((f"Support {idx+1}", k))
    for idx, k in enumerate(dylan): wallets.append((f"Partner {idx+1}", k))
    
    print(f"\n🔍 Scanning {len(wallets)} wallets for assets...\n")
    
    for label, key in wallets:
        try:
            from solders.keypair import Keypair
            addr = str(Keypair.from_base58_string(key).pubkey())
            
            sol = get_balance(rpc_url, addr)
            tokens = list_tokens(rpc_url, addr)
            
            print(f"--- [{label}] {addr} ---")
            print(f"💰 SOL: {sol:.6f}")
            if not tokens:
                print("🪙 Tokens: None found.")
            else:
                for t in tokens:
                    print(f"🪙 Token: {t['amount']} | {t['mint'][:12]}... ({t['type']})")
            print("")
            
        except Exception as e:
            print(f"❌ Failed to process {label}: {e}\n")

if __name__ == "__main__":
    main()
