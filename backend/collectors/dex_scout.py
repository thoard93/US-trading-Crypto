import aiohttp
import asyncio
import logging
import time

class DexScout:
    def __init__(self):
        self.base_url = "https://api.dexscreener.com/latest/dex"
        self.logger = logging.getLogger(__name__)

    async def get_pair_data(self, chain_id, token_address):
        """Fetch data for a specific token/pair from DexScreener."""
        # Use simple tokens endpoint which is robust for token addresses
        url = f"{self.base_url}/tokens/{token_address}"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    if response.status == 200:
                        data = await response.json()
                        pairs = data.get('pairs', [])
                        if not pairs:
                            return None
                        # Sort by liquidity to get the main pair
                        pairs.sort(key=lambda x: float(x.get('liquidity', {}).get('usd', 0)), reverse=True)
                        return pairs[0]
                    else:
                        print(f"❌ DexScreener API error: {response.status} for {token_address}")
                        return None
        except Exception as e:
            print(f"❌ Error fetching DexScreener data for {token_address}: {e}")
            return None

    async def search_tokens(self, query):
        """Search for tokens on DexScreener."""
        url = f"{self.base_url}/search/?q={query}"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    if response.status == 200:
                        data = await response.json()
                        return data.get('pairs', [])
                    else:
                        self.logger.error(f"DexScreener Search error: {response.status}")
                        return []
        except Exception as e:
            self.logger.error(f"Error searching DexScreener: {e}")
            return []

    def extract_token_info(self, pair_data):
        """Extract relevant fields from DexScreener pair data."""
        if not pair_data:
            return None
            
        return {
            "symbol": pair_data.get('baseToken', {}).get('symbol'),
            "name": pair_data.get('baseToken', {}).get('name'),
            "address": pair_data.get('baseToken', {}).get('address'),
            "price_usd": float(pair_data.get('priceUsd', 0)),
            "price_change_5m": float(pair_data.get('priceChange', {}).get('m5', 0)),
            "price_change_1h": float(pair_data.get('priceChange', {}).get('h1', 0)),
            "volume_24h": float(pair_data.get('volume', {}).get('h24', 0)),
            "liquidity_usd": float(pair_data.get('liquidity', {}).get('usd', 0)),
            "market_cap": float(pair_data.get('fdv', 0)), # Use FDV as Market Cap proxy
            "url": pair_data.get('url'),
            "chain": pair_data.get('chainId')
        }

    async def get_latest_boosted_tokens(self):
        """Fetch tokens with the latest boosts."""
        url = "https://api.dexscreener.com/token-boosts/latest/v1"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    if response.status == 200:
                        return await response.json()
                    return []
        except Exception as e:
            self.logger.error(f"Error fetching boosted tokens: {e}")
            return []

    async def get_latest_token_profiles(self):
        """Fetch the latest token profiles."""
        url = "https://api.dexscreener.com/token-profiles/latest/v1"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    if response.status == 200:
                        return await response.json()
                    return []
        except Exception as e:
            self.logger.error(f"Error fetching token profiles: {e}")
            return []

    async def get_trending_solana_pairs(self, min_liquidity=2000, limit=50):
        """Fetch trending Solana pairs from DexScreener (Expanded scan)."""
        # Step 1: Get Latest Profiles (Trending/New)
        profiles = await self.get_latest_token_profiles()
        if not profiles:
            return []
            
        # Filter for Solana
        sol_profiles = [p for p in profiles if p.get('chainId') == 'solana']
        
        candidates = []
        # Step 2: Fetch detailed pair data for candidates
        # Increased scan depth from 30 to 100 to find more non-pump.fun tokens
        for p in sol_profiles[:100]:
            addr = p.get('tokenAddress')
            if not addr: continue
            
            # ALL TOKENS ALLOWED (Alpha Unlock)
            
            # Fetch Pair Data (Price, Liquidity)
            # This uses the 'tokens/{addr}' endpoint which is reliable
            pair = await self.get_pair_data('solana', addr)
            
            if not pair: continue
            
            # Apply Filters
            liq = float(pair.get('liquidity', {}).get('usd', 0))
            if liq < min_liquidity:
                continue
                
            # Allow it
            candidates.append(pair)
            
            if len(candidates) >= limit:
                break
        
                
        return candidates

    async def get_new_solana_pairs(self, max_age_hours=6, limit=10):
        """Fetch newly created Solana pairs (just launched gems)."""
        # DexScreener doesn't have a direct "new pairs" API, but token profiles are often new
        # We'll use boosted tokens as a proxy for activity
        boosted = await self.get_latest_boosted_tokens()
        if not boosted:
            return []
        
        # Filter for Solana only
        sol_pairs = [b for b in boosted if b.get('chainId') == 'solana']
        return sol_pairs[:limit]
