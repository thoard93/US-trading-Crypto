import os
import random
from typing import List, Optional
from solders.keypair import Keypair

class WalletManager:
    """
    Manages multiple Solana wallets for distributed operations (Bot Farm).
    
    Wallet Roles:
    - Main Wallets: Can launch tokens, run simulations. Set via SOLANA_PRIVATE_KEY (required)
                    and SOLANA_MAIN_KEYS (optional, comma-separated for partners like Dylan).
    - Support Wallets: Used for distributed buys, engagement, holder diversity.
                       Set via SOLANA_SUPPORT_KEYS (comma-separated).
    """
    
    def __init__(self):
        # Primary main wallet (from original env var)
        self.primary_key: Optional[str] = os.getenv('SOLANA_PRIVATE_KEY')
        if self.primary_key:
            self.primary_key = self.primary_key.strip()
        
        # Additional main wallets (e.g., Dylan's wallet)
        self.main_keys: List[str] = []
        if self.primary_key:
            self.main_keys.append(self.primary_key)
        
        main_str = os.getenv('SOLANA_MAIN_KEYS', '')
        if main_str:
            additional_mains = [k.strip() for k in main_str.split(',') if k.strip()]
            self.main_keys.extend(additional_mains)
        
        # Support wallets (for buys/comments)
        self.support_keys: List[str] = []
        support_str = os.getenv('SOLANA_SUPPORT_KEYS', '')
        if support_str:
            self.support_keys = [k.strip() for k in support_str.split(',') if k.strip()]
        
        print(f"💼 WalletManager: {len(self.main_keys)} main + {len(self.support_keys)} support wallets loaded.")

    # === Main Wallet Methods ===
    
    def get_main_key(self) -> Optional[str]:
        """Return the primary bot wallet key (first main)."""
        return self.primary_key

    def get_all_main_keys(self) -> List[str]:
        """Return all main wallet keys (for launching/simulation)."""
        return self.main_keys

    def get_random_main_key(self) -> Optional[str]:
        """Return a random main wallet (useful for round-robin launches)."""
        if not self.main_keys:
            return None
        return random.choice(self.main_keys)

    # === Support Wallet Methods ===
    
    def get_random_support_key(self) -> Optional[str]:
        """Return a random support wallet key for engagement or micro-buys."""
        if not self.support_keys:
            return self.primary_key  # Fallback to primary if no support keys
        return random.choice(self.support_keys)

    def get_all_support_keys(self) -> List[str]:
        """Return all support keys (excluding mains)."""
        return self.support_keys

    # === Combined Methods ===
    
    def get_all_keys(self) -> List[str]:
        """Return all keys (mains + supports)."""
        return self.main_keys + self.support_keys

    def get_all_non_primary_keys(self) -> List[str]:
        """Return all keys except the primary (for bundled buys/engagement)."""
        all_keys = self.main_keys[1:] + self.support_keys  # Skip first main
        return all_keys

    # === Utility Methods ===
    
    def get_keypair(self, private_key: str) -> Keypair:
        """Convert a private key string (base58) to a Keypair object."""
        return Keypair.from_base58_string(private_key)

    @staticmethod
    def get_public_address(private_key: str) -> str:
        """Get the public address for a private key."""
        try:
            kp = Keypair.from_base58_string(private_key)
            return str(kp.pubkey())
        except Exception:
            return "unknown"
