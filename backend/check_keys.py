import os
import base64
from dotenv import load_dotenv

def diag():
    load_dotenv()
    print("\n--- 🔍 BOT DIAGNOSTICS ---")
    
    # 1. Discord Token
    token = os.getenv('DISCORD_TOKEN', '')
    if not token:
        print("❌ DISCORD_TOKEN: Missing")
    else:
        parts = token.split('.')
        print(f"✅ DISCORD_TOKEN: Found (Len: {len(token)}, Parts: {len(parts)})")
        if len(parts) != 3:
            print(f"   ⚠️ WARNING: Discord tokens usually have 3 parts (dots). Yours has {len(parts)}.")
        
    # 2. Solana Private Key
    sol_key = os.getenv('SOLANA_PRIVATE_KEY', '')
    if not sol_key:
        print("❌ SOLANA_PRIVATE_KEY: Missing")
    else:
        # Base58 check
        invalid = [c for c in sol_key if c in '0OI1'] # Note: 1 and I are often swapped
        # Actually 1 is allowed in Base58. I and l are not.
        base58_invalid = [c for c in sol_key if c in '0OlI']
        print(f"✅ SOLANA_PRIVATE_KEY: Found (Len: {len(sol_key)})")
        if base58_invalid:
            print(f"   ❌ ERROR: Found invalid Base58 characters: {set(base58_invalid)}")
        if len(sol_key) != 88:
            print(f"   ⚠️ WARNING: Solana Base58 keys are usually 88 characters. Yours is {len(sol_key)}.")

    print("--------------------------\n")

if __name__ == "__main__":
    diag()
