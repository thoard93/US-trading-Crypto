"""
Pump.fun Movers Scraper - Phase 57
Scrapes low MC movers directly from pump.fun website using residential proxy.
"""
import requests
import os
import re
import json
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()

def get_session():
    """Get a requests session with residential proxy if available."""
    session = requests.Session()
    proxy_url = os.getenv('RESIDENTIAL_PROXY')
    if proxy_url:
        session.proxies = {'http': proxy_url, 'https': proxy_url}
        print("🌐 Using residential proxy")
    else:
        print("⚠️ No proxy configured")
    return session

def scrape_pump_board():
    """Scrape the main pump.fun board for tokens."""
    session = get_session()
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
    }
    
    print("\n" + "="*80)
    print("🔍 SCRAPING PUMP.FUN BOARD")
    print("="*80)
    
    try:
        # Try the main board page
        resp = session.get('https://pump.fun/board', headers=headers, timeout=20)
        print(f"Status: {resp.status_code}")
        print(f"Content-Type: {resp.headers.get('content-type', 'unknown')}")
        print(f"Content Length: {len(resp.text)} chars")
        
        if resp.status_code == 200:
            # Check if we got HTML
            if 'text/html' in resp.headers.get('content-type', ''):
                soup = BeautifulSoup(resp.text, 'html.parser')
                
                # Print page title
                title = soup.find('title')
                print(f"Page Title: {title.text if title else 'None'}")
                
                # Look for token cards/items
                # pump.fun likely uses React, so look for data in script tags
                scripts = soup.find_all('script')
                print(f"\nFound {len(scripts)} script tags")
                
                found_tokens = False
                
                # Search ALL scripts for token-related JSON
                for idx, script in enumerate(scripts):
                    script_text = script.string or ''
                    
                    # Look for __NEXT_DATA__ 
                    if script.get('id') == '__NEXT_DATA__':
                        print(f"\n✅ Found __NEXT_DATA__ at script #{idx}")
                        try:
                            data = json.loads(script_text)
                            print(f"Keys: {list(data.keys())[:5]}")
                            # Deep search for tokens
                            found_tokens = search_for_tokens(data, "NEXT_DATA")
                        except:
                            pass
                    
                    # Look for any script containing token keywords
                    keywords = ['usd_market_cap', 'market_cap', '"mint":', '"symbol":', 'virtualSolReserves']
                    for kw in keywords:
                        if kw in script_text:
                            print(f"\n🎯 Found '{kw}' in script #{idx} ({len(script_text)} chars)")
                            
                            # Try to extract JSON arrays
                            for match in re.finditer(r'(\[[\s\S]*?\])', script_text):
                                try:
                                    arr = json.loads(match.group(1))
                                    if isinstance(arr, list) and len(arr) > 0 and isinstance(arr[0], dict):
                                        if any(k in arr[0] for k in ['mint', 'symbol', 'market_cap', 'usd_market_cap']):
                                            print(f"  ✅ Found token array with {len(arr)} items!")
                                            for i, t in enumerate(arr[:8]):
                                                symbol = t.get('symbol', t.get('name', '?'))
                                                mc = t.get('usd_market_cap', t.get('market_cap', 0))
                                                mint = t.get('mint', '?')[:16]
                                                print(f"    {i+1}. {symbol:12} | MC: ${mc:>12,.0f} | {mint}...")
                                            found_tokens = True
                                            break
                                except:
                                    pass
                            
                            # Also try extracting JSON objects
                            for match in re.finditer(r'(\{[^\{\}]{100,10000}\})', script_text):
                                try:
                                    obj = json.loads(match.group(1))
                                    if 'mint' in obj and ('symbol' in obj or 'market_cap' in obj):
                                        print(f"  Found single token: {obj.get('symbol', '?')}")
                                except:
                                    pass
                            break  # Only report once per script
                
                if not found_tokens:
                    print("\n⚠️ No embedded token data found in scripts")
                    print("Checking raw HTML for clues...")
                    # Look for data attributes
                    html_preview = resp.text[:5000]
                    if 'data-' in html_preview:
                        attrs = re.findall(r'data-[\w-]+', html_preview)
                        print(f"Data attributes found: {set(attrs)}")
                
                # Check for specific elements that might contain tokens
                token_els = soup.find_all(attrs={'data-token': True}) or soup.find_all(class_=re.compile(r'token|card|coin', re.I))
                if token_els:
                    print(f"\n✅ Found {len(token_els)} token elements by class/attr!")
                    
            else:
                print(f"Response preview: {resp.text[:500]}")
                
        else:
            print(f"Error: {resp.text[:500]}")
            
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()


def scrape_pump_advanced():
    """
    Advanced scraping using curl_cffi for TLS fingerprint impersonation.
    This better mimics a real browser and can bypass some Cloudflare checks.
    """
    try:
        from curl_cffi import requests as curl_requests
        print("\n" + "="*80)
        print("🔍 ADVANCED SCRAPE WITH CURL_CFFI (Chrome Impersonation)")
        print("="*80)
        
        proxy_url = os.getenv('RESIDENTIAL_PROXY')
        proxies = {'http': proxy_url, 'https': proxy_url} if proxy_url else None
        
        # Use Chrome impersonation
        resp = curl_requests.get(
            'https://pump.fun/board',
            impersonate="chrome120",
            proxies=proxies,
            timeout=20
        )
        
        print(f"Status: {resp.status_code}")
        print(f"Content Length: {len(resp.text)} chars")
        
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, 'html.parser')
            title = soup.find('title')
            print(f"Page Title: {title.text if title else 'None'}")
            
            # Look for __NEXT_DATA__
            for script in soup.find_all('script'):
                if script.get('id') == '__NEXT_DATA__':
                    print("✅ Found __NEXT_DATA__!")
                    data = json.loads(script.text)
                    
                    # Pretty print structure
                    def explore(obj, prefix=""):
                        if isinstance(obj, dict):
                            for k, v in obj.items():
                                if isinstance(v, (dict, list)):
                                    print(f"{prefix}{k}: {type(v).__name__}")
                                    if len(prefix) < 10:  # Limit depth
                                        explore(v, prefix + "  ")
                                else:
                                    val_str = str(v)[:50]
                                    print(f"{prefix}{k}: {val_str}")
                        elif isinstance(obj, list) and obj:
                            print(f"{prefix}[0]: {type(obj[0]).__name__} (len={len(obj)})")
                            if isinstance(obj[0], dict):
                                explore(obj[0], prefix + "  ")
                    
                    explore(data)
                    break
                    
    except ImportError:
        print("\n⚠️ curl_cffi not installed. Run: pip3 install curl_cffi")
    except Exception as e:
        print(f"❌ Error: {e}")


if __name__ == "__main__":
    scrape_pump_board()
    scrape_pump_advanced()
