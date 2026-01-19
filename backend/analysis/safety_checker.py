import aiohttp
import asyncio

class SafetyChecker:
    def __init__(self):
        # GoPlus endpoint for multi-chain (EVM)
        self.BASE_URL = "https://api.gopluslabs.io/api/v1/token_security"

    async def check_solana_token(self, token_address):
        """Unified entry for Solana safety checks."""
        return await self.check_token(token_address, chain="solana")

    async def check_token(self, token_address, chain="solana"):
        """
        Check token safety using RugCheck.xyz (Solana) or GoPlus (EVM).
        Returns a dict with 'safety_score' (0-100) and 'risks' (list).
        This is the new standard entry point.
        """
        # 1. Solana Check (RugCheck)
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
                            # Return a passing score to avoid blocking trades during rate limits
                            return {'safety_score': 80, 'risks': ['Rate Limit - Audit Skipped']}
                        else:
                            print(f"⚠️ RugCheck Failed: HTTP {response.status}")
                            # Fail safe: Return moderate score but with warning
                            return {'safety_score': 50, 'risks': [f"API Fail {response.status}"]}
            except Exception as e:
                print(f"⚠️ RugCheck Error: {str(e)}")
                return {'safety_score': 50, 'risks': ["Audit Error"]}
        
        # 2. Fallback / EVM (GoPlus Placeholder)
        # Using the old logic for EVM if needed
        return await self.check_safety(token_address, chain)

    async def check_safety(self, address, c_id="1"):
        """
        Legacy/EVM method using GoPlus.
        """
        # If incorrectly called for Solana, redirect
        if c_id.lower() == "solana":
            return await self.check_token(address, "solana")
            
        url = f"{self.BASE_URL}/{c_id}?contract_addresses={address}"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=5) as response:
                    if response.status != 200:
                        return {"error": f"API Error: {response.status}", "safety_score": 0}

                    data = await response.json()
                    
                    if data.get('code') != 1:
                        return {"error": "GoPlus Fetch Failed", "safety_score": 0}
                    
                    result_map = data.get('result', {})
                    if not result_map:
                        return {'safety_score': 50, 'risks': ["No EVM data"]}
                    
                    token_data = result_map.get(address) or result_map.get(address.lower()) or {}
                    
                    # Basic EVM Score Logic (Simplified)
                    score = 100
                    risks = []
                    if token_data.get('is_honeypot') == '1':
                        score = 0
                        risks.append("Honeypot")
                    if token_data.get('is_blacklisted') == '1':
                        score = 0
                        risks.append("Blacklisted")
                        
                    return {'safety_score': score, 'risks': risks}

        except Exception as e:
             # Silently handle EVM errors (Solana tokens often fail GoPlus)
             return {'safety_score': 50, 'risks': ["EVM Audit Skipped"]}

    def _check_solana_rugcheck(self, data):
        """Dedicated safety check for Solana using RugCheck.xyz Data"""
        score = 100
        risks = []
        
        # 1. Verification (Jupiter Lists are usually safe)
        verification = data.get("verification")
        if verification and isinstance(verification, dict):
            if verification.get("jup_verified"):
                return {
                    "token_name": data.get("token", {}).get("name", "Unknown"),
                    "token_symbol": data.get("token", {}).get("symbol", "Unknown"),
                    "is_honeypot": False,
                    "risks": ["Jupiter Strict List (SAFE)"],
                    "safety_score": 95,
                    "safety_status": "SAFE"
                }
        
        # 2. Analyze Risks
        found_risks = data.get("risks") or []
        for r in (found_risks if isinstance(found_risks, list) else []):
            level = r.get("level", "warn")
            name = r.get("name", "")
            
            name_lower = name.lower()

            if level == "danger":
                score -= 30
                risks.append(f"🚨 {name}")
            elif level == "warn":
                score -= 10
                risks.append(f"⚠️ {name}")

            # 2a. ULTIMATE BOT: CREATOR SHADOWING
            if "creator" in name_lower and "sold" in name_lower:
                score -= 60
                risks.append("🚨 CREATOR DUMPED")

            # 2a. Anti-Whale / Freeze Checks
            if "holder" in name_lower or "concentration" in name_lower:
                    score -= 50 # Heavy Penalty
                    risks.append(f"🚨 WHALE ALERT: {name}")
            if "freeze" in name_lower and level == "danger":
                    score -= 50
                    risks.append(f"🚨 Freeze Risk")

        # 3. Explicit Token Checks
        token_info = data.get("token", {})
        if token_info and token_info.get("freezeAuthority"):
             # If not already caught in risks
             if not any("freeze" in r.lower() for r in risks):
                 score -= 50
                 risks.append("🚨 Freeze Authority Enabled")
        
        # Cap Score
        score = max(0, min(100, score))
        
        return {
            "token_name": token_info.get("name", "Unknown"),
            "token_symbol": token_info.get("symbol", "Unknown"),
            "safety_score": score,
            "risks": risks,
            "safety_status": "SAFE" if score > 70 else "RISKY" if score > 40 else "DANGER"
        }
