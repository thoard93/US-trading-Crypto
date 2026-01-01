import aiohttp
import json

class SafetyChecker:
    """
    Checks token security using the GoPlus Security API.
    Supports major chains like Ethereum (1), BSC (56), Arbitrum (42161), etc.
    """
    BASE_URL = "https://api.gopluslabs.io/api/v1/token_security"

    def __init__(self):
        self.chain_map = {
            "ETH": "1",
            "BSC": "56",
            "ARB": "42161",
            "BASE": "8453",
            "OPT": "10"
        }

    async def check_token(self, address, chain_id="1"):
        """
        Fetch security data for a specific token address.
        Returns a dict with processed safety flags.
        """
        url = f"{self.BASE_URL}/{chain_id}?contract_addresses={address}"
        
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(url) as response:
                    data = await response.json()
                    if data.get('code') != 1:
                        return {"error": "Could not fetch data from GoPlus"}
                    
                    # GoPlus returns data in a map with address as key
                    token_data = data.get('result', {}).get(address.lower(), {})
                    return self._process_data(token_data)
            except Exception as e:
                return {"error": str(e)}

    def _process_data(self, data):
        """Extract key safety metrics from GoPlus response."""
        if not data:
            return {"error": "No data found for this address"}

        is_honeypot = data.get('is_honeypot') == "1"
        buy_tax = float(data.get('buy_tax', 0)) * 100
        sell_tax = float(data.get('sell_tax', 0)) * 100
        is_proxy = data.get('is_proxy') == "1"
        owner_can_mint = data.get('can_take_back_ownership') == "1" or data.get('is_mintable') == "1"
        is_whitelisted = data.get('is_white_list') == "1" # Risk if only whitelist can sell

        # Risk Score Calculation (Simple)
        risk_score = 0
        risks = []

        if is_honeypot:
            risk_score += 100
            risks.append("🚨 HONEYPOT DETECTED (Cannot sell)")
        if buy_tax > 10: risks.append(f"⚠️ High Buy Tax: {buy_tax}%")
        if sell_tax > 10: risks.append(f"⚠️ High Sell Tax: {sell_tax}%")
        if owner_can_mint: risks.append("⚠️ Owner can mint more tokens")
        if is_proxy: risks.append("⚠️ Proxy Contract (logic can be changed)")
        
        # Determine overall safety
        safety_status = "SAFE"
        if risk_score >= 100 or is_honeypot:
            safety_status = "DANGEROUS"
        elif len(risks) > 2:
            safety_status = "CAUTION"

        return {
            "token_name": data.get('token_name', 'Unknown'),
            "token_symbol": data.get('token_symbol', 'Unknown'),
            "is_honeypot": is_honeypot,
            "buy_tax": f"{buy_tax}%",
            "sell_tax": f"{sell_tax}%",
            "risks": risks,
            "safety_status": safety_status
        }

if __name__ == "__main__":
    # Test for a known token (e.g. USDT on Ethereum)
    import asyncio
    checker = SafetyChecker()
    # async def test():
    #     res = await checker.check_token("0xdac17f958d2ee523a2206206994597c13d831ec7", "1")
    #     print(json.dumps(res, indent=2))
    # asyncio.run(test())
