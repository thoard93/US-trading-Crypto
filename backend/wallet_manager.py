import os
import random
from typing import List, Optional
from solders.keypair import Keypair

class WalletManager:
    """
    Manages multiple Solana wallets for distributed operations (Bot Farm).
    - Main Wallet: Used for launching and major volume.
    - Support Wallets: Used for distributed volume, engagement, and holder diversity.
    """
    
    def __init__(self):
        self.main_key: Optional[str] = os.getenv('SOLANA_PRIVATE_KEY')
        self.support_keys: List[str] = []
        
        # Load support keys from comma-separated list
        support_str = os.getenv('SOLANA_SUPPORT_KEYS', '')
        if support_str:
            # Clean up whitespace and split
            self.support_keys = [k.strip() for k in support_str.split(',') if k.strip()]
            
        print(f"💼 WalletManager: Loaded 1 main and {len(self.support_keys)} support wallets.")

    def get_main_key(self) -> Optional[str]:
        """Return the primary bot wallet key."""
        return self.main_key

    def get_random_support_key(self) -> Optional[str]:
        """Return a random support wallet key for engagement or micro-buys."""
        if not self.support_keys:
            return self.main_key # Fallback to main if no support keys
        return random.choice(self.support_keys)

    def get_all_support_keys(self) -> List[str]:
        """Return all support keys (excluding main)."""
        return self.support_keys

    def get_all_keys(self) -> List[str]:
        """Return all keys including main."""
        all_keys = []
        if self.main_key:
            all_keys.append(self.main_key)
        all_keys.extend(self.support_keys)
        return all_keys

    def get_keypair(self, private_key: str) -> Keypair:
        """Convert a private key string (base58) to a Keypair object."""
        import base58
        return Keypair.from_base58_string(private_key)

    @staticmethod
    def get_public_address(private_key: str) -> str:
        """Get the public address for a private key."""
        try:
            import base58
            kp = Keypair.from_base58_string(private_key)
            return str(kp.pubkey())
        except Exception:
            return "unknown"
