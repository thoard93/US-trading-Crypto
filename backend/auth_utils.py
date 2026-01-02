import os
import requests
from dotenv import load_dotenv

load_dotenv()

DISCORD_CLIENT_ID = os.getenv("DISCORD_CLIENT_ID", "").strip()
DISCORD_CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET", "").strip()
DISCORD_REDIRECT_URI = os.getenv("DISCORD_REDIRECT_URI", "http://localhost:8000/auth/discord/callback").strip()

DISCORD_API_BASE = "https://discord.com/api"
DISCORD_AUTH_URL = f"{DISCORD_API_BASE}/oauth2/authorize"
DISCORD_TOKEN_URL = f"{DISCORD_API_BASE}/oauth2/token"
DISCORD_USER_URL = f"{DISCORD_API_BASE}/users/@me"

if not DISCORD_CLIENT_ID or not DISCORD_CLIENT_SECRET:
    print("⚠️ WARNING: Discord Client ID or Secret is missing from environment variables!")

def get_discord_auth_url():
    """Generate the Discord authorization URL."""
    import urllib.parse
    params = {
        "client_id": DISCORD_CLIENT_ID,
        "redirect_uri": DISCORD_REDIRECT_URI,
        "response_type": "code",
        "scope": "identify email"
    }
    return f"{DISCORD_AUTH_URL}?{urllib.parse.urlencode(params)}"

def get_discord_token(code):
    """Exchange auth code for access token using standard form body."""
    # Reverting to payload body as it's often more compatible with cloud proxy layers
    data = {
        "client_id": DISCORD_CLIENT_ID,
        "client_secret": DISCORD_CLIENT_SECRET,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": DISCORD_REDIRECT_URI
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    
    print(f"📡 Requesting Discord Token with ID: {DISCORD_CLIENT_ID[:4]}... and URI: {DISCORD_REDIRECT_URI}")
    response = requests.post(DISCORD_TOKEN_URL, data=data, headers=headers)
    
    # Detailed logging for debugging invalid_client
    if response.status_code != 200:
        print(f"❌ Discord Token Error ({response.status_code}): {response.text}")
        
    return response.json()

def get_discord_user(access_token):
    """Fetch user info using access token."""
    headers = {"Authorization": f"Bearer {access_token}"}
    response = requests.get(DISCORD_USER_URL, headers=headers)
    return response.json()
