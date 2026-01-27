"""
Trend Hunter - Discovers viral keywords from trending tokens and social media.
Used by the Auto-Launch pipeline to find meme-worthy keywords.
"""
import os
import re
import logging
import requests
import time
from datetime import datetime, timedelta

class TrendHunter:
    """
    Scans multiple sources for trending keywords suitable for meme coins.
    """
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.anthropic_key = os.getenv('ANTHROPIC_API_KEY', '').strip()
        self.twitter_bearer = os.getenv('TWITTER_BEARER_TOKEN', '').strip()
        
        # Blacklist of terms to never launch (safety)
        self.blacklist = {
            'nsfw', 'porn', 'xxx', 'hate', 'nazi', 'racist', 'terror',
            'kill', 'murder', 'suicide', 'child', 'kids', 'minor',
            'scam', 'rug', 'fraud', 'hack', 'exploit'
        }
        
        # Cache to avoid duplicate API calls
        self._last_dex_fetch = None
        self._dex_cache = []
        self._last_twitter_fetch = None
        self._twitter_cache = []
        self._last_pump_fetch = None
        self._pump_cache = []
        self._cache_duration = 300  # 5 minutes
    
    def get_trending_keywords(self, limit=10, with_source=False):
        """
        Main entry point: Get trending keywords from all sources.
        Returns list of unique, filtered keywords.
        If with_source=True, returns list of dicts: [{'keyword': 'X', 'source': 'pump'}, ...]
        """
        keywords_with_source = []  # List of (keyword, source) tuples
        
        # Source 1: Pump.fun Movers (PRIMARY - most relevant for pump.fun launches)
        pump_keywords = self._get_pumpfun_movers()
        for kw in pump_keywords:
            keywords_with_source.append((kw, 'pump'))
        
        # Source 2: DexScreener Trending Tokens
        dex_keywords = self._get_dexscreener_keywords()
        for kw in dex_keywords:
            keywords_with_source.append((kw, 'dex'))
        
        # Source 3: Token Profiles (Paid Boosted Tokens)
        profile_keywords = self._get_token_profile_keywords()
        for kw in profile_keywords:
            keywords_with_source.append((kw, 'dex'))
        
        # Source 4: Twitter/X Trending (if available)
        if self.twitter_bearer:
            twitter_keywords = self._get_twitter_trending()
            for kw in twitter_keywords:
                keywords_with_source.append((kw, 'twitter'))
        
        # Deduplicate by keyword (keep first source encountered)
        seen = set()
        unique_keywords = []
        for kw, source in keywords_with_source:
            if kw not in seen:
                seen.add(kw)
                unique_keywords.append({'keyword': kw, 'source': source})
        
        # Filter and rank (uses just the keyword strings for filtering)
        keyword_strings = [item['keyword'] for item in unique_keywords]
        filtered_strings = self._filter_keywords(keyword_strings)
        
        # Rebuild with sources, preserving filter order
        filtered_with_source = []
        source_map = {item['keyword']: item['source'] for item in unique_keywords}
        for kw in filtered_strings:
            if kw in source_map:
                filtered_with_source.append({'keyword': kw, 'source': source_map[kw]})
        
        self.logger.info(f"🔍 Found {len(filtered_with_source)} trending keywords")
        
        result = filtered_with_source[:limit]
        
        # Return format based on with_source flag
        if with_source:
            return result
        else:
            # Backwards compatible: return just keyword strings
            return [item['keyword'] for item in result]
    
    def _get_pumpfun_movers(self):
        """Extract trending keywords from Pump.fun movers/top-runners."""
        try:
            # Use cache if fresh
            now = time.time()
            if self._last_pump_fetch and (now - self._last_pump_fetch) < self._cache_duration:
                return self._pump_cache
            
            # Try multiple Pump.fun API endpoints
            endpoints = [
                "https://frontend-api.pump.fun/coins/top-runners",
                "https://frontend-api-v3.pump.fun/coins/top-runners",
                "https://frontend-api.pump.fun/coins/trending"
            ]
            
            tokens = []
            for endpoint in endpoints:
                try:
                    resp = requests.get(endpoint, timeout=10, headers={
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                    })
                    if resp.status_code == 200:
                        data = resp.json()
                        # Handle different response formats
                        if isinstance(data, list):
                            tokens = data[:30]
                        elif isinstance(data, dict):
                            tokens = data.get('coins', data.get('data', []))[:30]
                        break
                except Exception as e:
                    self.logger.debug(f"Pump.fun endpoint {endpoint} failed: {e}")
                    continue
            
            if not tokens:
                self.logger.warning("Could not fetch Pump.fun movers from any endpoint")
                return self._pump_cache  # Return stale cache
            
            keywords = []
            theme_counter = {}  # Track theme frequency
            
            for token in tokens:
                # Extract name and symbol
                name = token.get('name', '') or token.get('token_name', '')
                symbol = token.get('symbol', '') or token.get('ticker', '')
                description = token.get('description', '')
                
                # Extract words from name
                words = self._extract_words(name)
                keywords.extend(words)
                
                # Extract words from description
                desc_words = self._extract_words(description)
                keywords.extend(desc_words)
                
                # Add symbol if it's a word
                if len(symbol) >= 3 and symbol.isalpha():
                    keywords.append(symbol.upper())
                
                # Track common themes for pattern detection
                for word in words:
                    word_lower = word.lower()
                    if word_lower in theme_counter:
                        theme_counter[word_lower] += 1
                    else:
                        theme_counter[word_lower] = 1
            
            # Log detected themes (words appearing 2+ times = trending theme)
            trending_themes = [k for k, v in theme_counter.items() if v >= 2]
            if trending_themes:
                self.logger.info(f"🔥 Pump.fun trending themes detected: {trending_themes[:5]}")
            
            # Update cache
            self._last_pump_fetch = now
            self._pump_cache = list(set(keywords))
            
            self.logger.info(f"🚀 Pump.fun: Found {len(self._pump_cache)} trending keywords")
            return self._pump_cache
            
        except Exception as e:
            self.logger.error(f"Error fetching Pump.fun movers: {e}")
            return self._pump_cache  # Return stale cache
    
    def _get_twitter_trending(self):
        """Get trending topics from Twitter/X."""
        try:
            # Use cache if fresh
            now = time.time()
            if self._last_twitter_fetch and (now - self._last_twitter_fetch) < self._cache_duration:
                return self._twitter_cache
            
            # Twitter API v2 - Get US trends (WOEID 23424977)
            url = "https://api.twitter.com/2/trends/by/woeid/23424977"
            headers = {"Authorization": f"Bearer {self.twitter_bearer}"}
            
            resp = requests.get(url, headers=headers, timeout=10)
            
            if resp.status_code == 200:
                data = resp.json()
                trends = data.get('data', [])
                
                keywords = []
                for trend in trends[:20]:
                    name = trend.get('trend_name', '')
                    # Remove # from hashtags
                    name = name.lstrip('#')
                    words = self._extract_words(name)
                    keywords.extend(words)
                
                self._last_twitter_fetch = now
                self._twitter_cache = list(set(keywords))
                self.logger.info(f"🐦 Twitter: Found {len(self._twitter_cache)} trending keywords")
                return self._twitter_cache
                
            elif resp.status_code == 429:
                self.logger.warning("🐦 Twitter rate limited")
                return self._twitter_cache  # Return cached
            else:
                self.logger.warning(f"🐦 Twitter API error: {resp.status_code}")
                return []
                
        except Exception as e:
            self.logger.error(f"Twitter error: {e}")
            return []
    
    def _get_dexscreener_keywords(self):
        """Extract keywords from DexScreener trending Solana tokens."""
        try:
            # Use cache if fresh
            now = time.time()
            if self._last_dex_fetch and (now - self._last_dex_fetch) < self._cache_duration:
                return self._dex_cache
            
            # Fetch trending pairs
            resp = requests.get(
                "https://api.dexscreener.com/latest/dex/search?q=solana",
                timeout=10
            )
            
            if resp.status_code != 200:
                self.logger.warning(f"DexScreener API returned {resp.status_code}")
                return []
            
            data = resp.json()
            pairs = data.get('pairs', [])[:30]  # Top 30 pairs
            
            keywords = []
            for pair in pairs:
                base = pair.get('baseToken', {})
                name = base.get('name', '')
                symbol = base.get('symbol', '')
                
                # Extract words from name
                words = self._extract_words(name)
                keywords.extend(words)
                
                # Add symbol if it looks like a word
                if len(symbol) >= 3 and symbol.isalpha():
                    keywords.append(symbol.upper())
            
            # Update cache
            self._last_dex_fetch = now
            self._dex_cache = list(set(keywords))
            
            return self._dex_cache
            
        except Exception as e:
            self.logger.error(f"Error fetching DexScreener: {e}")
            return []
    
    def _get_token_profile_keywords(self):
        """Extract keywords from DexScreener Token Profiles (boosted tokens)."""
        try:
            resp = requests.get(
                "https://api.dexscreener.com/token-profiles/latest/v1",
                timeout=10
            )
            
            if resp.status_code != 200:
                return []
            
            profiles = resp.json()
            solana_profiles = [p for p in profiles if p.get('chainId') == 'solana'][:20]
            
            keywords = []
            for profile in solana_profiles:
                # Token profiles don't always have name, use description or header
                desc = profile.get('description', '')
                header = profile.get('header', '')
                
                words = self._extract_words(desc) + self._extract_words(header)
                keywords.extend(words)
            
            return list(set(keywords))
            
        except Exception as e:
            self.logger.error(f"Error fetching Token Profiles: {e}")
            return []
    
    def _extract_words(self, text):
        """Extract meaningful words from text."""
        if not text:
            return []
        
        # Remove special characters, keep letters and spaces
        clean = re.sub(r'[^a-zA-Z\s]', ' ', text)
        words = clean.split()
        
        # Filter: 3-15 chars, not common words
        common_words = {
            'the', 'and', 'for', 'are', 'but', 'not', 'you', 'all',
            'can', 'had', 'her', 'was', 'one', 'our', 'out', 'has',
            'his', 'how', 'its', 'may', 'new', 'now', 'old', 'see',
            'way', 'who', 'boy', 'did', 'get', 'let', 'put', 'say',
            'she', 'too', 'use', 'coin', 'token', 'crypto', 'solana',
            'with', 'this', 'that', 'from', 'have', 'will', 'your',
            'more', 'when', 'make', 'like', 'just', 'over', 'such',
            'looking', 'faithfulness', 'hallmark', 'straight', 'waited',
            'about', 'there', 'their', 'which', 'would', 'could', 'should',
            'every', 'everyone', 'everything', 'something', 'anything',
            'really', 'think', 'thought', 'people', 'going', 'been', 'want'
        }
        
        result = []
        for word in words:
            word = word.strip().upper()
            if 3 <= len(word) <= 15 and word.lower() not in common_words:
                result.append(word)
        
        return result
    
    def _filter_keywords(self, keywords):
        """Filter and PRIORITIZE keywords based on proven Pump.fun patterns."""
        filtered = []
        
        # 🔥 HOT META JANUARY 2026: AI/Agent keywords get priority boost
        ai_boost_terms = {
            'ai', 'agent', 'bot', 'gpt', 'llm', 'neural', 'brain', 'auto',
            'robo', 'cyber', 'algo', 'smart', 'machine', 'deep', 'cognitive',
            'npc', 'sentient', 'conscious', 'synthetic', 'agentic', 'terminal'
        }
        
        # Absurdist/crude humor (FARTCOIN tier) - also gets boost
        absurd_boost_terms = {
            'fart', 'poop', 'burp', 'hiccup', 'sneeze', 'yawn', 'chonk',
            'thicc', 'giga', 'mega', 'ultra', 'turbo', 'maxi', 'lord',
            'king', 'god', 'chad', 'degen', 'ape', 'moon', 'wagmi'
        }
        
        priority_keywords = []
        normal_keywords = []
        
        for keyword in keywords:
            kw_lower = keyword.lower()
            
            # Check blacklist
            if any(bad in kw_lower for bad in self.blacklist):
                continue
            
            # Must be reasonable length
            if len(keyword) < 3 or len(keyword) > 15:
                continue
            
            # Must be mostly letters
            if not keyword.replace(' ', '').isalpha():
                continue
            
            # 🎯 PRIORITY CHECK: AI/Agent or Absurdist terms go first
            # Use exact word matching to avoid "STRAIGHT" matching "AI"
            words_in_kw = set(kw_lower.split())
            is_priority = any(term in words_in_kw for term in ai_boost_terms) or \
                          any(term in words_in_kw for term in absurd_boost_terms)
            
            if is_priority:
                priority_keywords.append(keyword.upper())
            else:
                normal_keywords.append(keyword.upper())
        
        # Combine: priority first, then normal
        combined = priority_keywords + normal_keywords
        
        # Remove duplicates while preserving order
        seen = set()
        unique = []
        for kw in combined:
            if kw not in seen:
                seen.add(kw)
                unique.append(kw)
        
        if priority_keywords:
            self.logger.info(f"🔥 Priority keywords (AI/Absurdist meta): {priority_keywords[:5]}")
        
        return unique
    
    def is_meme_worthy(self, keyword):
        """
        Use AI to determine if a keyword is meme-worthy.
        Returns True if it's suitable for a viral meme coin.
        """
        if not self.anthropic_key:
            # No AI available, accept all filtered keywords
            return True
        
        try:
            from anthropic import Anthropic
            client = Anthropic(api_key=self.anthropic_key)
            
            prompt = f"""
            Evaluate if this keyword would make a good viral meme coin on pump.fun: "{keyword}"
            
            Consider:
            - Is it funny, edgy, or culturally relevant?
            - Would crypto degens find it appealing?
            - Is it trending or related to current events?
            - Would it get attention on social media?
            
            Respond with ONLY "YES" or "NO" (nothing else).
            """
            
            response = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=10,
                messages=[{"role": "user", "content": prompt}]
            )
            
            answer = response.content[0].text.strip().upper()
            return answer == "YES"
            
        except Exception as e:
            self.logger.error(f"AI filter error: {e}")
            return True  # Default to accepting if AI fails
    
    def get_best_keyword(self):
        """
        Get the single best keyword for launching right now.
        Filters through all sources and uses AI to pick the winner.
        """
        keywords = self.get_trending_keywords(limit=10)
        
        if not keywords:
            self.logger.warning("No trending keywords found")
            return None
        
        # If we have AI, use it to pick the best one
        if self.anthropic_key:
            for keyword in keywords:
                if self.is_meme_worthy(keyword):
                    return keyword
        
        # Fallback: return the first one
        return keywords[0] if keywords else None


# Test script
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    hunter = TrendHunter()
    
    print("🔍 Hunting for trending keywords...")
    keywords = hunter.get_trending_keywords(limit=10)
    
    print(f"\n📊 Found {len(keywords)} keywords:")
    for i, kw in enumerate(keywords, 1):
        print(f"  {i}. {kw}")
    
    best = hunter.get_best_keyword()
    print(f"\n🏆 Best keyword for launch: {best}")
