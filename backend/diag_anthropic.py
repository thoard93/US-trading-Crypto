import os
import json
from dotenv import load_dotenv
from anthropic import Anthropic

# 1. Load the .env file (Robust pathing)
script_dir = os.path.dirname(os.path.abspath(__file__))
env_path = os.path.join(script_dir, '.env')
load_dotenv(env_path)

key = os.getenv('ANTHROPIC_API_KEY')

print("--- ANTHROPIC KEY DIAGNOSTIC ---")
if not key:
    print("❌ ERROR: ANTHROPIC_API_KEY not found in .env")
else:
    # Aggressive cleaning (same as bot logic)
    clean_key = "".join(key.split())
    clean_key = clean_key.strip("'").strip('"')
    
    print(f"✅ Key Found in .env")
    print(f"📊 Length: {len(clean_key)}")
    print(f"🔍 Snippet: {clean_key[:15]}...{clean_key[-4:]}")

    # 2. Try a simple call
    print("\n📡 Testing connection to Claude...")
    try:
        client = Anthropic(api_key=clean_key)
        message = client.messages.create(
            model="claude-3-5-sonnet-20240620",
            max_tokens=10,
            messages=[{"role": "user", "content": "Hello"}]
        )
        print("✅ SUCCESS: Claude responded!")
        print(f"💬 Response: {message.content[0].text}")
    except Exception as e:
        print(f"❌ FAILED: Anthropic API returned an error:")
        print(f"   {str(e)}")
        if "401" in str(e):
             print("\n💡 TIP: 401 usually means the KEY is wrong or the account has NO CREDITS.")
             print("   Double check you don't have a typo in the .env value.")
print("--------------------------------")
