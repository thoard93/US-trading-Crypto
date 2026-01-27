"""
Pump.fun Movers Deep Research Script
Analyzes metrics AND trade patterns to detect wash trading/coordination
Run on VPS: python movers_research.py
"""
import requests
import json
from datetime import datetime
from collections import Counter
import time

def fetch_movers():
    """Fetch current movers from Pump.fun API"""
    endpoints = [
        "https://frontend-api.pump.fun/coins/top-runners",
        "https://frontend-api-v3.pump.fun/coins/top-runners",
    ]
    
    for endpoint in endpoints:
        try:
            resp = requests.get(endpoint, timeout=10, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            })
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, list):
                    return data
                elif isinstance(data, dict):
                    return data.get('coins', data.get('data', []))
        except Exception as e:
            print(f"Endpoint {endpoint} failed: {e}")
            continue
    return []

def fetch_token_trades(mint_address, limit=50):
    """Fetch recent trades for a token to analyze patterns"""
    try:
        # Pump.fun trades endpoint
        url = f"https://frontend-api.pump.fun/trades/latest?mint={mint_address}&limit={limit}"
        resp = requests.get(url, timeout=10, headers={
            'User-Agent': 'Mozilla/5.0'
        })
        if resp.status_code == 200:
            return resp.json()
    except Exception as e:
        pass
    
    # Fallback: Try coin details
    try:
        url = f"https://frontend-api.pump.fun/coins/{mint_address}"
        resp = requests.get(url, timeout=10, headers={
            'User-Agent': 'Mozilla/5.0'
        })
        if resp.status_code == 200:
            return resp.json()
    except:
        pass
    
    return None

def analyze_trade_patterns(trades, symbol):
    """Detect wash trading / bot patterns in trades"""
    if not trades or not isinstance(trades, list):
        return {"pattern": "NO_DATA", "score": 0}
    
    wallets = []
    amounts = []
    timestamps = []
    is_buys = []
    
    for trade in trades:
        wallet = trade.get('user', trade.get('wallet', trade.get('trader', '')))
        if wallet:
            wallets.append(wallet[:8])  # First 8 chars
        amount = trade.get('sol_amount', trade.get('amount', 0))
        amounts.append(float(amount) if amount else 0)
        ts = trade.get('timestamp', trade.get('block_timestamp', 0))
        timestamps.append(ts)
        is_buy = trade.get('is_buy', trade.get('side', '') == 'buy')
        is_buys.append(is_buy)
    
    if not wallets:
        return {"pattern": "NO_WALLETS", "score": 0}
    
    # DETECTION METRICS
    results = {
        "total_trades": len(trades),
        "unique_wallets": len(set(wallets)),
    }
    
    # 1. WALLET CONCENTRATION (Few wallets = wash trading)
    wallet_counts = Counter(wallets)
    top_wallet_trades = wallet_counts.most_common(1)[0][1] if wallet_counts else 0
    results["top_wallet_pct"] = (top_wallet_trades / len(trades)) * 100 if trades else 0
    
    # 2. REPEAT TRADER RATIO
    repeat_traders = sum(1 for w, c in wallet_counts.items() if c > 1)
    results["repeat_trader_pct"] = (repeat_traders / len(set(wallets))) * 100 if wallets else 0
    
    # 3. AMOUNT CONSISTENCY (Same amounts = bot)
    amount_counts = Counter([round(a, 4) for a in amounts if a > 0])
    if amount_counts:
        most_common_amt = amount_counts.most_common(1)[0]
        results["repeated_amount"] = most_common_amt[0]
        results["repeated_amount_count"] = most_common_amt[1]
        results["amount_repetition_pct"] = (most_common_amt[1] / len(amounts)) * 100
    
    # 4. BUY/SELL RATIO
    buy_count = sum(1 for b in is_buys if b)
    sell_count = len(is_buys) - buy_count
    results["buy_pct"] = (buy_count / len(is_buys)) * 100 if is_buys else 50
    
    # 5. TIMING ANALYSIS (trades per minute - high = bot)
    if len(timestamps) >= 2 and timestamps[0] and timestamps[-1]:
        try:
            time_span_sec = abs(timestamps[0] - timestamps[-1]) / 1000  # ms to sec
            if time_span_sec > 0:
                results["trades_per_min"] = (len(trades) / time_span_sec) * 60
        except:
            pass
    
    # WASH TRADING SCORE (0-100, higher = more suspicious)
    score = 0
    flags = []
    
    if results.get("top_wallet_pct", 0) > 30:
        score += 30
        flags.append(f"TOP_WALLET_{results['top_wallet_pct']:.0f}%")
    
    if results.get("repeat_trader_pct", 0) > 50:
        score += 20
        flags.append(f"REPEAT_TRADERS_{results['repeat_trader_pct']:.0f}%")
    
    if results.get("amount_repetition_pct", 0) > 40:
        score += 25
        flags.append(f"SAME_AMOUNTS_{results['amount_repetition_pct']:.0f}%")
    
    if results.get("buy_pct", 50) > 85:
        score += 15
        flags.append(f"BUY_HEAVY_{results['buy_pct']:.0f}%")
    
    if results.get("trades_per_min", 0) > 10:
        score += 10
        flags.append(f"FAST_TRADING_{results.get('trades_per_min', 0):.1f}/min")
    
    results["wash_score"] = score
    results["flags"] = flags
    results["verdict"] = "LIKELY_BOT" if score >= 50 else "MIXED" if score >= 25 else "ORGANIC"
    
    return results

def analyze_movers(tokens):
    """Deep analysis of movers with trade pattern detection"""
    if not tokens:
        print("No tokens fetched!")
        return
    
    print(f"\n{'='*100}")
    print(f"PUMP.FUN MOVERS DEEP ANALYSIS - {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"Checking for wash trading, bots, and coordination patterns")
    print(f"{'='*100}")
    print(f"Total tokens on movers: {len(tokens)}\n")
    
    # Categorize findings
    likely_bots = []
    organic = []
    mixed = []
    
    for i, token in enumerate(tokens[:20]):  # Analyze top 20
        name = token.get('name', 'Unknown')[:25]
        symbol = token.get('symbol', '?')
        mint = token.get('mint', token.get('address', ''))
        mc = token.get('market_cap', 0)
        usd_mc = token.get('usd_market_cap', 0)
        replies = token.get('reply_count', 0)
        
        mc_display = f"${usd_mc:,.0f}" if usd_mc else f"{mc:,.0f}"
        
        print(f"\n{'-'*100}")
        print(f"#{i+1} {symbol} | MC: {mc_display} | Replies: {replies} | {name}")
        print(f"Mint: {mint[:20]}..." if mint else "Mint: Unknown")
        
        # Fetch and analyze trades
        if mint:
            trades = fetch_token_trades(mint)
            if trades:
                analysis = analyze_trade_patterns(trades if isinstance(trades, list) else [], symbol)
                
                print(f"  Trades: {analysis.get('total_trades', 0)} | Unique Wallets: {analysis.get('unique_wallets', 0)}")
                print(f"  Top Wallet: {analysis.get('top_wallet_pct', 0):.0f}% of trades")
                print(f"  Repeat Traders: {analysis.get('repeat_trader_pct', 0):.0f}%")
                print(f"  Buy Ratio: {analysis.get('buy_pct', 50):.0f}%")
                
                if analysis.get('repeated_amount'):
                    print(f"  Most Common Amount: {analysis['repeated_amount']} SOL ({analysis.get('repeated_amount_count', 0)}x)")
                
                if analysis.get('trades_per_min'):
                    print(f"  Trade Speed: {analysis['trades_per_min']:.1f} trades/min")
                
                # Verdict
                verdict = analysis.get('verdict', 'UNKNOWN')
                wash_score = analysis.get('wash_score', 0)
                flags = ', '.join(analysis.get('flags', []))
                
                if verdict == "LIKELY_BOT":
                    print(f"  >>> VERDICT: BOT/WASH TRADING (Score: {wash_score}/100)")
                    print(f"      Flags: {flags}")
                    likely_bots.append(symbol)
                elif verdict == "MIXED":
                    print(f"  >>> VERDICT: MIXED SIGNALS (Score: {wash_score}/100)")
                    print(f"      Flags: {flags}")
                    mixed.append(symbol)
                else:
                    print(f"  >>> VERDICT: LIKELY ORGANIC (Score: {wash_score}/100)")
                    organic.append(symbol)
            else:
                print("  [Could not fetch trade data]")
        
        time.sleep(0.5)  # Rate limit
    
    # Summary
    print(f"\n{'='*100}")
    print("SUMMARY: MOVERS TAB COMPOSITION")
    print(f"{'='*100}")
    print(f"LIKELY BOT/WASH: {len(likely_bots)} tokens - {', '.join(likely_bots)}")
    print(f"MIXED SIGNALS:   {len(mixed)} tokens - {', '.join(mixed)}")
    print(f"LIKELY ORGANIC:  {len(organic)} tokens - {', '.join(organic)}")
    print(f"\nBOT PERCENTAGE: {(len(likely_bots) / (len(likely_bots) + len(mixed) + len(organic))) * 100:.0f}% of movers")
    
    # Print available fields
    if tokens:
        print(f"\n{'='*100}")
        print("API FIELDS AVAILABLE")
        print(f"{'='*100}")
        for key, value in tokens[0].items():
            val_preview = str(value)[:60] if value else "null"
            print(f"  {key}: {val_preview}")

if __name__ == "__main__":
    print("Fetching Pump.fun movers data for deep analysis...")
    tokens = fetch_movers()
    analyze_movers(tokens)
