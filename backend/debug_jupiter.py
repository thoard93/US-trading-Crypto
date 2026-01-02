
import requests
import json

def test_jupiter_quote(input_mint, output_mint, amount_lamports, slippage_bps=100):
    # url = "https://quote-api.jup.ag/v6/quote" # Failed DNS
    url = "https://public.jupiterapi.com/quote" # Alternative
    params = {
        "inputMint": input_mint,
        "outputMint": output_mint,
        "amount": str(amount_lamports),
        "slippageBps": slippage_bps,
        "onlyDirectRoutes": "false"
    }
    
    print(f"Requesting Quote: {params}")
    try:
        response = requests.get(url, params=params)
        print(f"Status Code: {response.status_code}")
        
        if response.status_code == 200:
            print("Response:")
            print(json.dumps(response.json(), indent=2))
        else:
            print("Error Response:")
            print(response.text)
    except Exception as e:
        print(f"Exception: {e}")

if __name__ == "__main__":
    SOL_MINT = "So11111111111111111111111111111111111111112"
    # Correct BOME Address: ukHH6c7mMyiWCf1b9pnWe25TSpkDDt3H5pQZgZ74J82
    BOME_MINT = "ukHH6c7mMyiWCf1b9pnWe25TSpkDDt3H5pQZgZ74J82" 
    BONK_MINT = "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263"
    
    # Test valid quote for BONK first (known good)
    print("--- Testing BONK Quote (0.01 SOL) ---")
    test_jupiter_quote(SOL_MINT, BONK_MINT, 10000000) # 0.01 SOL

    print("\n--- Testing BOME Quote (0.01 SOL) ---")
    test_jupiter_quote(SOL_MINT, BOME_MINT, 10000000) # 0.01 SOL
