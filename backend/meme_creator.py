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
        Analyze the viral potential of the keyword: "{keyword}"
        Generate a meme coin profile for pump.fun.
        
        Requirements:
        1. Name: Catchy, viral, max 20 chars.
        2. Ticker: 3-5 chars, uppercase.
        3. Simple Description: 1 sentence, funny/edgy.
        4. Logo Prompt: A detailed artistic prompt for an AI image generator. 
           Focus on 'nano-banana-pro' style: sharp 2K quality, centered character, minimalist but high impact.
        
        Return ONLY a JSON object:
        {{
            "name": "...",
            "ticker": "...",
            "description": "...",
            "logo_prompt": "..."
        }}
        """
        
        try:
            response = self.client.messages.create(
                model="claude-3-5-sonnet-20241022",
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
                
            return json.loads(content)
        except Exception as e:
            self.logger.error(f"Error generating meme pack: {e}")
            return None

    def generate_logo(self, prompt):
        """
        Uses Kie AI (Nano Banana Pro) to generate a 2K logo.
        """
        if not self.kie_ai_key:
            self.logger.warning("🚫 KIE_AI_API_KEY not found. Image generation disabled.")
            return None
            
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
                "resolution": "2K",
                "output_format": "png"
            }
        }
        
        try:
            # 1. Create Task
            response = requests.post(url, headers=headers, json=payload, timeout=15)
            result = response.json()
            
            if result.get('code') != 200:
                self.logger.error(f"Kie AI Task Creation Failed: {result}")
                return None
                
            task_id = result['data']['taskId']
            self.logger.info(f"🎨 Kie AI Task Created: {task_id}")
            
            # 2. Poll for Result (wait up to 60s)
            poll_url = f"https://api.kie.ai/api/v1/jobs/queryTask?taskId={task_id}"
            for _ in range(12): # 12 * 5s = 60s
                time.sleep(5)
                poll_resp = requests.get(poll_url, headers=headers, timeout=10)
                poll_result = poll_resp.json()
                
                if poll_result.get('code') == 200:
                    state = poll_result['data'].get('state')
                    if state == 'success':
                        # The result is in resultJson
                        res_json = json.loads(poll_result['data'].get('resultJson', '{}'))
                        image_url = res_json.get('resultUrls', [None])[0]
                        self.logger.info(f"✅ Logo Generated: {image_url}")
                        return image_url
                    elif state == 'fail':
                        self.logger.error(f"❌ Kie AI Task Failed: {poll_result['data'].get('failMsg')}")
                        return None
                else:
                    self.logger.error(f"Kie AI Poll Error: {poll_result}")
                    return None
                    
            self.logger.warning("⏳ Kie AI Generation Timeout")
            return None
        except Exception as e:
            self.logger.error(f"Error generating logo via Kie AI: {e}")
            return None

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
