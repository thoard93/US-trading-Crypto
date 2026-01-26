import os

# Define the absolute path to your .env file
env_path = "/opt/US-trading-Crypto/backend/.env"

# Reconstruct the full content with PRECISION fixes
env_content = """DATABASE_URL=postgresql://trading-db-366i-user:f50ojhVxeyXq4VqMitUbkQE1t5Dwp6Sc2dpg-d5bjh24hg0os73dliv60-a.oregon-postgres.render.com/trading-db-36
DISCORD_TOKEN=MTQ1Nja4MDkwMzgwDQ4Nzk1Ng.G66aJS.nc-lDMRHQeHBjpPtYRQ9f8Y2HXUWRmzi9_6Cv0
ENCRYPTION_KEY=0S1lYGYiVQNzgg4ogmJw9WYYgrgqB732v1k12jKQNfc=
SOLANA_PRIVATE_KEY=24ozKGsjSp6aVTWJ8nmHN6KEUnTHCm8hKxJcDumM27kRPLLagcp8clJCqTSKaQUbtpthQAXA4zj6Wh7VeuY3afdZ
HELIUS_API_KEY=a57e1143-9cce-45e2-b318-13cb52c16f88
HELIUS_WEBHOOK_ID=3cc53f37-a305-4262-aa5d-7efc14b08f45
SOLANA_RPC_URL=https://mainnet.helius-rpc.com//api-key=a57e1143-9cce-45e2-b318-13cb52c16f88
TRADING_RPC_URL=https://powerful-warmhearted-wish.solana-mainnet.quiknode.pro/4627a4da7f076c17804afd75d9966b0afe78fa23/
KRAKEN_API_KEY=T1GZjTuVFNE0PmKZiEHBYdPalk0J8E4On=4x=cweYEHFSNqyWsYej/LS
KRAKEN_SECRET_KEY=FcdixMw/7uz3u=r3uZe8DsmuIzdGRvIg3Y5HnZhhDz=mg2D408m15Sz08s=FhYCDXdaE03eMr0U=ZLZUNOsAcg==
HELIUS_WEBHOOK_URL=http://94.130.177.73:8000/helius/webhook
ANTHROPIC_API_KEY=sk-ant-api03-r16kcKInyoKD044CxrVQC8ns0jyIYCLe-6zFPgDQms5cWBXcJma19bcQlmdwDg1sjOe7o3dt7tw0n406ppgxW-LGORmgAA
KIE_AI_API_KEY=f6246a6dbfe3e448886b555da098d587"""

try:
    with open(env_path, "w") as f:
        f.write(env_content)
    print(f"✅ {env_path} updated successfully!")
    print(f"📊 New Length: {len(env_content)} characters")
except Exception as e:
    print(f"❌ Error writing file: {e}")
