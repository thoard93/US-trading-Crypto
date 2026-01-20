import aiohttp
import asyncio
import logging
import time

class DexScout:
    def __init__(self):
        self.base_url = "https://api.dexscreener.com/latest/dex"
        self.logger = logging.getLogger(__name__)

    async def _get(self, url):
        """Internal helper for DexScreener GET requests with 429 backoff."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    if response.status == 200:
                        return await response.json()
                    elif response.status == 429:
                        self.logger.warning(f"🛑 DexScreener Rate Limit (429) hit. Backing off... URL: {url[:64]}")
                        # Return a specific marker so callers can handle it
                        return "429"
                    else:
                        self.logger.error(f"DexScreener API error {response.status} for {url[:64]}")
                        return None
        except Exception as e:
            self.logger.error(f"DexScreener connection error: {e}")
            return None

    async def get_pair_data(self, chain_id, token_address):
        """Fetch data for a specific token/pair from DexScreener."""
        url = f"{self.base_url}/tokens/{token_address}"
        data = await self._get(url)
        
        if data == "429":
            return None # Callers handle the lag
            
        if data:
            pairs = data.get('pairs', [])
            if not pairs:
                return None
            # Sort by liquidity to get the main pair
            pairs.sort(key=lambda x: float(x.get('liquidity', {}).get('usd', 0)), reverse=True)
            return pairs[0]
        return None

    async def search_tokens(self, query):
        """Search for tokens on DexScreener."""
        url = f"{self.base_url}/search/?q={query}"
        data = await self._get(url)
        if data and data != "429":
            return data.get('pairs', [])
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
        data = await self._get(url)
        if data and data != "429":
            return data
        return []

    async def get_latest_token_profiles(self):
        """Fetch the latest token profiles."""
        url = "https://api.dexscreener.com/token-profiles/latest/v1"
        data = await self._get(url)
        if data and data != "429":
            return data
        return []

    async def get_token_pairs_bulk(self, token_addresses):
        """Fetch data for multiple tokens in a single request (Max 30)."""
        if not token_addresses:
            return []
            
        addrs_str = ",".join(token_addresses)
        url = f"{self.base_url}/tokens/{addrs_str}"
        data = await self._get(url)
        
        if data == "429":
             return "429"
             
        if data:
            return data.get('pairs', [])
        return []

    async def get_trending_solana_pairs(self, min_liquidity=2000, limit=50):
        """Fetch trending Solana pairs from DexScreener using Bulk Lookups."""
        profiles = await self.get_latest_token_profiles()
        if not profiles:
            return []
            
        sol_profiles = [p for p in profiles if p.get('chainId') == 'solana']
        addrs = [p.get('tokenAddress') for p in sol_profiles[:100] if p.get('tokenAddress')]
        
        candidates = []
        # Step 2: Fetch detailed pair data in batches of 30 (API limit)
        for i in range(0, len(addrs), 30):
            batch = addrs[i:i+30]
            pairs = await self.get_token_pairs_bulk(batch)
            
            if pairs == "429":
                print("🛑 DexScreener Rate Limit hit. Cooling down for 30s...")
                await asyncio.sleep(30)
                break # Exit early but return what we have
                
            if not pairs: continue
            
            for pair in pairs:
                liq = float(pair.get('liquidity', {}).get('usd', 0))
                if liq >= min_liquidity:
                    candidates.append(pair)
            
            if len(candidates) >= limit:
                break
                
            await asyncio.sleep(1) # Tiny pause between batches for safety
                
        return candidates[:limit]

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
