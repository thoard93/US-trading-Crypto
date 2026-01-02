import aiohttp
import asyncio
import logging

class DexScout:
    def __init__(self):
        self.base_url = "https://api.dexscreener.com/latest/dex"
        self.logger = logging.getLogger(__name__)

    async def get_pair_data(self, chain_id, pair_address):
        """Fetch data for a specific pair from DexScreener."""
        url = f"{self.base_url}/pairs/{chain_id}/{pair_address}"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    if response.status == 200:
                        data = await response.json()
                        return data.get('pair')
                    else:
                        self.logger.error(f"DexScreener API error: {response.status}")
                        return None
        except Exception as e:
            self.logger.error(f"Error fetching DexScreener data: {e}")
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
            "url": pair_data.get('url'),
            "chain": pair_data.get('chainId')
        }
