import os
import requests
import json
import time
import logging
from anthropic import Anthropic

class MemeCreator:
    """
    The 'Creative Engine' for Phase 6.
    Uses AI to generate viral coin concepts and Kie AI for 2K logos.
    """
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        # 🛡️ RESILIENCE: Remove ALL whitespace/newlines from terminal copy-pastes
        self.anthropic_key = os.getenv('ANTHROPIC_API_KEY', '')
        self.anthropic_key = "".join(self.anthropic_key.split()) if self.anthropic_key else None
        if self.anthropic_key:
            self.anthropic_key = self.anthropic_key.strip("'").strip('"')
        
        self.kie_ai_key = os.getenv('KIE_AI_API_KEY', '')
        self.kie_ai_key = "".join(self.kie_ai_key.split()) if self.kie_ai_key else None
        
        if self.anthropic_key:
            # 🛡️ DEBUG: Verify key length and format (masked)
            start_snippet = self.anthropic_key[:15]
            end_snippet = self.anthropic_key[-4:]
            print(f"🧠 AI Brain: Loading Anthropic Key (Len: {len(self.anthropic_key)}, Starts: {start_snippet}..., Ends: ...{end_snippet})")
            self.client = Anthropic(api_key=self.anthropic_key)
        else:
            self.client = None
            self.logger.warning("🚫 ANTHROPIC_API_KEY not found. Meme generation disabled.")

    def generate_meme_pack(self, keyword):
        """
        Uses Claude to generate Name, Ticker, and Logo Prompt.
        """
        if not self.client:
            return None
            
        prompt = f"""
        You are a viral meme coin naming expert and master of unhinged internet subculture. 
        Analyze the keyword: "{keyword}"
        Generate a meme coin profile optimized for absolute maximum FOMO and Pump.fun graduation.
        
        PROVEN VIRAL NAMING PATTERNS (use one):
        1. UNHINGED/REACTIONARY: Over-the-top, slightly cursed, or aggressive takes on current trends.
        2. ABSURDIST HUMOR: Crude/bodily humor or nonsense words (FARTCOIN, BURP, GIGAFART).
        3. TREND-RIDER: Variations of whatever is blowing up (e.g., if DOGE is up, launch SHY DOGE).
        4. AI/AGENT: Sentient agent vibes, terminal output aesthetic (GOAT, AGENTIC, TRUTH).
        5. VIBE/MOOD: Relatable degen lifestyle or extreme laziness (CHILLGUY, COZYMAXI).
        
        STRICT REQUIREMENTS:
        - Name: Max 15 chars. MUST BE UNHINGED, funny, or extremely catchy. Think "PUMPKIN SPICE WHITE GIRL" or "CHAD WIF DUMBBELL".
        - Ticker: EXACTLY 3-5 characters, uppercase only. NO EXCEPTIONS. If keyword has a known ticker pattern (e.g., INU), try to incorporate it.
        - Description: 1 punchy, edgy, or absurd sentence that makes people want to ape in. Use degen slang (moon, ape, wagmi, pump).
        - Logo Prompt: Must specify "unhinged mascot" + specific neon color palette + slightly cursed/funny expression + highly detailed 2K mascot character.
        
        Return ONLY valid JSON:
        {{
            "name": "...",
            "ticker": "...",
            "description": "...",
            "logo_prompt": "..."
        }}
        """
        
        try:
            response = self.client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=500,
                messages=[{"role": "user", "content": prompt}]
            )
            
            # Extract JSON from response
            content = response.content[0].text
            # Basic JSON extraction in case Claude adds markdown
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "{" in content:
                content = content[content.find("{"):content.rfind("}")+1]
            
            pack = json.loads(content)
            
            # 🎯 TICKER VALIDATION: Enforce 3-5 chars (critical for Pump.fun success)
            ticker = pack.get('ticker', 'MEME').upper().replace('$', '')
            if len(ticker) < 3:
                ticker = ticker + 'X' * (3 - len(ticker))  # Pad short tickers
            elif len(ticker) > 5:
                ticker = ticker[:5]  # Truncate long tickers
            pack['ticker'] = ticker
            
            # 🎯 NAME VALIDATION: Max 15 chars
            name = pack.get('name', 'MemeCoin')
            if len(name) > 15:
                pack['name'] = name[:15]
            
            return pack
        except Exception as e:
            self.logger.error(f"Error generating meme pack: {e}")
            return None

    def generate_logo(self, prompt):
        """
        Uses a multi-tier image cascade for maximum reliability.
        Priority: Kie AI → Replicate SDXL → Pollinations.AI → DiceBear
        """
        # Tier 1: Kie AI (Nano Banana Pro) - Best quality, slowest
        if self.kie_ai_key:
            result = self._try_kie_ai(prompt)
            if result:
                return result
        
        # Tier 2: Replicate SDXL Lightning - Great quality, fast, cheap
        replicate_key = os.getenv('REPLICATE_API_KEY', '').strip()
        if replicate_key:
            result = self._try_replicate(prompt, replicate_key)
            if result:
                return result
        
        # Tier 3: Pollinations.AI - Good quality, FREE, no API key
        result = self._try_pollinations(prompt)
        if result:
            return result
        
        # Tier 4: DiceBear - Basic placeholder (always works)
        self.logger.warning("⚠️ All image sources failed. Using placeholder.")
        return self._get_placeholder_image()
    
    def _try_kie_ai(self, prompt):
        """Attempt Kie AI generation with 5 minute timeout."""
        url = "https://api.kie.ai/api/v1/jobs/createTask"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.kie_ai_key}"
        }
        payload = {
            "model": "nano-banana-pro",
            "input": {
                "prompt": prompt,
                "aspect_ratio": "1:1",
                "resolution": "1K",
                "output_format": "png"
            }
        }
        
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=15)
            result = response.json()
            
            # 🔍 DEBUG: Log full response
            self.logger.info(f"🎨 Kie AI Create Response: {result}")
            
            if result.get('code') != 200:
                self.logger.error(f"Kie AI Task Creation Failed: {result}")
                return None
                
            task_id = result['data']['taskId']
            self.logger.info(f"🎨 Kie AI Task Created: {task_id}")
            
            # Poll for 5 minutes (60 attempts × 5s)
            poll_url = f"https://api.kie.ai/api/v1/jobs/recordInfo?taskId={task_id}"
            
            for attempt in range(60):
                time.sleep(5)
                try:
                    poll_resp = requests.get(poll_url, headers=headers, timeout=10)
                    poll_result = poll_resp.json()
                    
                    # 🔍 DEBUG: Log every 6th poll (every 30s)
                    if attempt % 6 == 0:
                        self.logger.info(f"🔄 Kie AI Poll {attempt+1}/60: {poll_result}")
                    
                    if poll_result.get('code') == 200:
                        data = poll_result.get('data', {})
                        state = data.get('state', '').lower()
                        
                        # ✅ SUCCESS STATES: Both 'success' and 'completed' are valid
                        if state in ['success', 'completed']:
                            res_json_str = data.get('resultJson', '{}')
                            res_json = json.loads(res_json_str) if isinstance(res_json_str, str) else res_json_str
                            
                            # Try multiple possible URL locations
                            image_url = None
                            if 'resultUrls' in res_json and res_json['resultUrls']:
                                image_url = res_json['resultUrls'][0]
                            elif 'url' in res_json:
                                image_url = res_json['url']
                            elif 'imageUrl' in res_json:
                                image_url = res_json['imageUrl']
                            elif 'output' in data:
                                image_url = data['output']
                            
                            if image_url:
                                self.logger.info(f"✅ Kie AI Logo Generated: {image_url}")
                                return image_url
                            else:
                                self.logger.warning(f"⚠️ Kie AI Success but no URL found in: {data}")
                                
                        elif state in ['fail', 'failed', 'error']:
                            self.logger.error(f"❌ Kie AI Task Failed: {data.get('failMsg', data)}")
                            return None
                        # 'pending', 'processing', 'running' - continue polling
                        
                except Exception as poll_err:
                    self.logger.warning(f"⚠️ Kie AI Poll Error (attempt {attempt+1}): {poll_err}")
                    continue
                    
            self.logger.warning("⏳ Kie AI Timeout (5 min). Trying fallback...")
            return None
            
        except Exception as e:
            self.logger.error(f"Kie AI Error: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def _try_replicate(self, prompt, api_key):
        """Attempt Replicate SDXL Lightning generation."""
        try:
            url = "https://api.replicate.com/v1/predictions"
            headers = {
                "Authorization": f"Token {api_key}",
                "Content-Type": "application/json"
            }
            payload = {
                "version": "5599ed30703defd1d160a25a63321b4dec97101d98b4674bcc56e41f62f35637",  # SDXL Lightning
                "input": {
                    "prompt": f"meme coin logo, {prompt}, centered, vibrant colors, high quality, 2K resolution",
                    "num_outputs": 1,
                    "width": 1024,
                    "height": 1024
                }
            }
            
            response = requests.post(url, headers=headers, json=payload, timeout=15)
            result = response.json()
            
            if 'urls' not in result:
                self.logger.error(f"Replicate API Error: {result}")
                return None
            
            # Poll for completion (max 60s)
            get_url = result['urls']['get']
            for attempt in range(12):
                time.sleep(5)
                poll_resp = requests.get(get_url, headers=headers, timeout=10)
                poll_result = poll_resp.json()
                
                if poll_result.get('status') == 'succeeded':
                    output = poll_result.get('output', [])
                    if output:
                        self.logger.info(f"✅ Replicate Logo Generated: {output[0][:50]}...")
                        return output[0]
                elif poll_result.get('status') == 'failed':
                    self.logger.error(f"❌ Replicate Failed: {poll_result.get('error')}")
                    return None
            
            self.logger.warning("⏳ Replicate Timeout. Trying fallback...")
            return None
            
        except Exception as e:
            self.logger.error(f"Replicate Error: {e}")
            return None
    
    def _try_pollinations(self, prompt):
        """Attempt Pollinations.AI generation (FREE, no API key)."""
        try:
            # Pollinations.AI is completely free and requires no API key
            encoded_prompt = requests.utils.quote(f"meme coin logo, {prompt}, centered, vibrant, high quality")
            url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1024&height=1024&nologo=true"
            
            # Test if the URL works (Pollinations generates on-demand)
            response = requests.head(url, timeout=30)
            if response.status_code == 200:
                self.logger.info(f"✅ Pollinations Logo Generated: {url[:50]}...")
                return url
            else:
                self.logger.warning(f"Pollinations returned status {response.status_code}")
                return None
                
        except Exception as e:
            self.logger.error(f"Pollinations Error: {e}")
            return None
    
    def _get_placeholder_image(self):
        """Returns a placeholder meme coin image URL using DiceBear avatar API."""
        import random
        import hashlib
        # Generate a random seed for unique placeholder each time
        seed = hashlib.md5(str(random.random()).encode()).hexdigest()[:8]
        # DiceBear bottts style - futuristic robot avatars perfect for meme coins
        return f"https://api.dicebear.com/7.x/bottts/png?seed={seed}&size=512&backgroundColor=0d1117"



    def create_full_meme(self, keyword):
        """
        Orchestrates full generation.
        """
        print(f"🧠 Analyzing trend: {keyword}...")
        pack = self.generate_meme_pack(keyword)
        if not pack:
            return None
            
        print(f"🎨 Generating 2K logo for {pack['name']}...")
        image_url = self.generate_logo(pack['logo_prompt'])
        
        if image_url:
            pack['image_url'] = image_url
            return pack
        
        return None

if __name__ == "__main__":
    # Test Script
    logging.basicConfig(level=logging.INFO)
    creator = MemeCreator()
    result = creator.create_full_meme("Ice Storm Warning")
    if result:
        print("\n🚀 MEME READY FOR PUMP.FUN:")
        print(json.dumps(result, indent=2))
    else:
        print("\n❌ Failed to generate meme.")
