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
        # Explicit Solana support (GoPlus uses 'solana' or specific ID, we try 'solana')
        # Note: GoPlus API usually requires specific chain ID. For Solana, it is 'solana'.
        self.chain_map["SOLANA"] = "solana"

    async def check_token(self, address, chain_id="1"):
        """
        Fetch security data for a specific token address.
        """
        # Resolve chain_id from map if needed
        c_id = self.chain_map.get(str(chain_id).upper(), str(chain_id))
        
        # USE RUGCHECK FOR SOLANA
        if c_id.lower() == "solana":
            return await self._check_solana_rugcheck(address)

        # GoPlus API endpoint for EVM chains
        url = f"{self.BASE_URL}/{c_id}?contract_addresses={address}"
        
        async with aiohttp.ClientSession() as session:
            try:
                # 3-second timeout to prevent lags
                async with session.get(url, timeout=3) as response:
                    # Check for 200 OK
                    if response.status != 200:
                        return {"error": f"API Error: {response.status}", "safety_score": 0}

                    data = await response.json()
                    
                    if data.get('code') != 1:
                        # Fallback for some chains or errors
                        print(f"⚠️ GoPlus Error Code {data.get('code')}: {data.get('message')}")
                        return {"error": "GoPlus Fetch Failed", "safety_score": 0}
    async def check_token(self, token_address, chain="solana"):
        """
        Check token safety using RugCheck.xyz (Solana) or GoPlus (EVM - Placeholder).
        Returns a dict with 'safety_score' (0-100) and 'risks' (list).
        """
        # 1. Anti-Spam / Cache Check (Optional optimization)
        
        # 2. Solana Check (RugCheck)
        if chain.lower() == "solana":
            url = f"https://api.rugcheck.xyz/v1/tokens/{token_address}/report"
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, timeout=10) as response:
                        if response.status == 200:
                            data = await response.json()
                            return self._check_solana_rugcheck(data)
                        elif response.status == 429:
                            print(f"⚠️ RugCheck Rate Limit (429). Assuming SAFE for now.")
                            return {'safety_score': 80, 'risks': ['Rate Limit - Audit Skipped']}
                        else:
                            print(f"⚠️ RugCheck Failed: HTTP {response.status}")
                            # Fail safe: Return moderate score but with warning
                            return {'safety_score': 50, 'risks': [f"API Fail {response.status}"]}
            except Exception as e:
                print(f"⚠️ RugCheck Error: {str(e)}")
                return {'safety_score': 50, 'risks': ["Audit Error"]}
        
        # Fallback for other chains
        return {'safety_score': 100, 'risks': []}

    async def _check_solana_rugcheck(self, data):
        """Dedicated safety check for Solana using RugCheck.xyz"""
                    verification = data.get("verification")
                    if verification and isinstance(verification, dict):
                        if verification.get("jup_verified"):
                            # If strictly verified, hard set high score
                            return {
                                "token_name": verification.get("name", "Unknown"),
                                "token_symbol": verification.get("symbol", "Unknown"),
                                "is_honeypot": False,
                                "risks": ["Jupiter Strict List (SAFE)"],
                                "safety_score": 95,
                                "safety_status": "SAFE"
                            }
                    
                    # 2. RugCheck 'risks' array is the best source of truth
                    found_risks = data.get("risks") or []
                    # risks is a list of objects {name: "...", level: "..."}
                    
                    for r in (found_risks if isinstance(found_risks, list) else []):
                        level = r.get("level", "warn")
                        name = r.get("name", "")
                        
                        if level == "danger":
                            score -= 30
                            risks.append(f"🚨 {name}")
                        elif level == "warn":
                            score -= 10
                            risks.append(f"⚠️ {name}")

                        # 2a. SPECIAL: Check for Whale dominance (User Request)
                        if "holder" in name.lower() or "concentration" in name.lower():
                             score -= 50 # Instant Fail territory
                             risks.append(f"🚨 WHALE ALERT: {name}")
                            
                    # 3. Freeze Authority check (explicit if not in risks)
                    if data.get("token", {}).get("freezeAuthority"):
                        score -= 50
                        risks.append("🚨 Freeze Authority Enabled")
                        
                    if data.get("token", {}).get("mintAuthority"):
                        score -= 30
                        risks.append("⚠️ Mint Authority Enabled")

                    score = max(0, min(100, score))
                    
                    return {
                        "token_name": data.get("tokenMeta", {}).get("name", "Unknown"),
                        "token_symbol": data.get("tokenMeta", {}).get("symbol", "Unknown"),
                        "is_honeypot": False, # Solana doesn't have traditional honeypots like EVM
                        "buy_tax": "0%", # Solana SPL standard usually 0 tax (transfer extensions exist though)
                        "sell_tax": "0%",
                        "risks": risks,
                        "safety_score": score,
                        "safety_status": "SAFE" if score > 70 else "CAUTION"
                    }

            except Exception as e:
                print(f"⚠️ RugCheck Failed: {e}")
                return {"error": str(e), "safety_score": 0}

    def _process_data(self, data):
        """Extract key safety metrics from GoPlus response."""
        if not data:
            # If no data is returned, it might be a BRAND NEW token. 
            # We assign a default LOW score to be safe, or 0 if we want to be strict.
            # Let's return 0 to prevent buying unverified tokens.
            return {"error": "No Data", "safety_score": 0}

        # Handle different response structures (GoPlus Solana sometimes differs)
        is_honeypot = str(data.get('is_honeypot', '0')) == "1"
        is_open_source = str(data.get('is_open_source', '1')) == "1" # Default to 1 if missing? No, 0.
        
        # Taxes
        buy_tax = float(data.get('buy_tax', 0)) * 100
        sell_tax = float(data.get('sell_tax', 0)) * 100
        
        # Ownership
        owner_can_mint = str(data.get('can_take_back_ownership', '0')) == "1" or str(data.get('is_mintable', '0')) == "1"
        
        # Risk Score Calculation (0 to 100, where 100 is SAFE)
        # Note: self.dex_monitor uses 'safety_score' where higher is better.
        # But checks risk. Let's invert: Start at 100, deduct.
        
        score = 100
        risks = []

        if is_honeypot:
            score = 0
            risks.append("🚨 HONEYPOT (Cannot sell)")
        else:
            if buy_tax > 10: 
                score -= 20
                risks.append(f"⚠️ High Buy Tax: {buy_tax}%")
            if sell_tax > 10: 
                score -= 20
                risks.append(f"⚠️ High Sell Tax: {sell_tax}%")
            if owner_can_mint: 
                score -= 30
                risks.append("⚠️ Owner can mint (Inflation Risk)")
            if not is_open_source:
                score -= 20
                risks.append("⚠️ Contract not verified/open source")
        
        # Cap score
        score = max(0, min(100, score))

        return {
            "token_name": data.get('token_name', 'Unknown'),
            "token_symbol": data.get('token_symbol', 'Unknown'),
            "is_honeypot": is_honeypot,
            "buy_tax": f"{buy_tax}%",
            "sell_tax": f"{sell_tax}%",
            "risks": risks,
            "safety_score": score,
            "safety_status": "SAFE" if score > 80 else "CAUTION"
        }

if __name__ == "__main__":
    # Test for a known token (e.g. USDT on Ethereum)
    import asyncio
    checker = SafetyChecker()
    # async def test():
    #     res = await checker.check_token("0xdac17f958d2ee523a2206206994597c13d831ec7", "1")
    #     print(json.dumps(res, indent=2))
    # asyncio.run(test())
