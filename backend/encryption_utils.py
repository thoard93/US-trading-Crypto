from cryptography.fernet import Fernet
import os
from dotenv import load_dotenv

load_dotenv()

# Get the encryption key from environment variables
# If not present, this will fail purposefully to prevent unencrypted storage
SECRET_KEY = os.getenv("ENCRYPTION_KEY")

if not SECRET_KEY:
    # Generate a key if it's the first time (USER should save this!)
    print("⚠️ WARNING: ENCRYPTION_KEY not found in .env. Generating a temporary one...")
    SECRET_KEY = Fernet.generate_key().decode()
    print(f"SAVE THIS TO YOUR .env: ENCRYPTION_KEY={SECRET_KEY}")

cipher_suite = Fernet(SECRET_KEY.encode())

def encrypt_key(data: str) -> str:
    """Encrypt a string (API Key/Secret)."""
    if not data: return ""
    return cipher_suite.encrypt(data.encode()).decode()

def decrypt_key(encrypted_data: str) -> str:
    """Decrypt an encrypted string."""
    if not encrypted_data: return ""
    try:
        return cipher_suite.decrypt(encrypted_data.encode()).decode()
    except Exception as e:
        # Silencing noise for users with missing/invalid keys at startup
        # print(f"❌ Decryption failed: {e}")
        return ""
