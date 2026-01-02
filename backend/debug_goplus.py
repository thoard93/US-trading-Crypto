
import aiohttp
import asyncio
import json

async def check_goplus(address):
    url = f"https://api.gopluslabs.io/api/v1/token_security/solana?contract_addresses={address}"
    print(f"Fetching GoPlus: {url}")
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            print(f"GoPlus Status: {response.status}")
            data = await response.json()
            print(json.dumps(data, indent=2))

async def check_rugcheck(address):
    url = f"https://api.rugcheck.xyz/v1/tokens/{address}/report"
    print(f"Fetching RugCheck: {url}")
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            print(f"RugCheck Status: {response.status}")
            if response.status == 200:
                data = await response.json()
                print(json.dumps(data, indent=2))
            else:
                print(await response.text())

if __name__ == "__main__":
    # BONK Address
    addr = "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263"
    asyncio.run(check_goplus(addr))
    print("-" * 50)
    asyncio.run(check_rugcheck(addr))
