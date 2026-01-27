"""
Pump.fun Movers Research - FIXED VERSION
Now with correct field parsing for v3 API
"""
import requests
import json
from datetime import datetime
from collections import Counter
import time

def fetch_movers():
    """Fetch current movers from Pump.fun API v3"""
    url = "https://frontend-api-v3.pump.fun/coins/top-runners"
    try:
        resp = requests.get(url, timeout=15, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'application/json',
        })
        if resp.status_code == 200:
            data = resp.json()
            # Extract the coin data from nested structure
            tokens = []
            for item in data:
                if isinstance(item, dict) and 'coin' in item:
                    coin = item['coin']
                    coin['trend_reason'] = item.get('description', '')  # Why it's trending
                    tokens.append(coin)
                elif isinstance(item, dict):
                    tokens.append(item)
            return tokens
    except Exception as e:
        print(f"Error fetching movers: {e}")
    return []

def fetch_token_trades(mint_address, limit=100):
    """Fetch recent trades for a token"""
    endpoints = [
        f"https://frontend-api-v3.pump.fun/trades/latest?mint={mint_address}&limit={limit}",
        f"https://frontend-api.pump.fun/trades/latest?mint={mint_address}&limit={limit}",
    ]
    for url in endpoints:
        try:
            resp = requests.get(url, timeout=10, headers={'User-Agent': 'Mozilla/5.0'})
            if resp.status_code == 200:
                return resp.json()
        except:
            continue
    return []

def analyze_trade_patterns(trades, symbol):
    """Detect wash trading / bot patterns"""
    if not trades or not isinstance(trades, list) or len(trades) == 0:
        return {"pattern": "NO_DATA", "wash_score": 0, "verdict": "UNKNOWN"}
    
    wallets = []
    amounts = []
    is_buys = []
    
    for trade in trades[:100]:
        wallet = trade.get('user', trade.get('wallet', trade.get('trader', '')))
        if wallet:
            wallets.append(wallet[:12])
        amount = trade.get('sol_amount', trade.get('amount', 0))
        try:
            amounts.append(float(amount) if amount else 0)
        except:
            amounts.append(0)
        is_buy = trade.get('is_buy', True)
        is_buys.append(is_buy)
    
    if not wallets:
        return {"pattern": "NO_WALLETS", "wash_score": 0, "verdict": "UNKNOWN"}
    
    results = {
        "total_trades": len(trades),
        "unique_wallets": len(set(wallets)),
    }
    
    # 1. WALLET CONCENTRATION
    wallet_counts = Counter(wallets)
    top_wallet = wallet_counts.most_common(1)[0] if wallet_counts else ('?', 0)
    results["top_wallet"] = top_wallet[0]
    results["top_wallet_trades"] = top_wallet[1]
    results["top_wallet_pct"] = (top_wallet[1] / len(wallets)) * 100
    
    # 2. REPEAT TRADERS
    repeat_traders = sum(1 for w, c in wallet_counts.items() if c > 2)
    results["repeat_traders"] = repeat_traders
    results["repeat_trader_pct"] = (repeat_traders / len(set(wallets))) * 100 if wallets else 0
    
    # 3. AMOUNT PATTERNS
    if amounts:
        rounded_amounts = [round(a, 3) for a in amounts if a > 0]
        if rounded_amounts:
            amount_counts = Counter(rounded_amounts)
            most_common = amount_counts.most_common(1)[0]
            results["common_amount"] = most_common[0]
            results["common_amount_count"] = most_common[1]
            results["amount_repetition_pct"] = (most_common[1] / len(rounded_amounts)) * 100
    
    # 4. BUY/SELL RATIO
    buy_count = sum(1 for b in is_buys if b)
    results["buy_pct"] = (buy_count / len(is_buys)) * 100 if is_buys else 50
    
    # WASH SCORE CALCULATION
    score = 0
    flags = []
    
    if results.get("top_wallet_pct", 0) > 25:
        score += 25
        flags.append(f"WHALE_{results['top_wallet_pct']:.0f}%")
    
    if results.get("repeat_trader_pct", 0) > 40:
        score += 20
        flags.append(f"REPEATS_{results['repeat_trader_pct']:.0f}%")
    
    if results.get("amount_repetition_pct", 0) > 30:
        score += 25
        flags.append(f"SAME_AMT_{results.get('amount_repetition_pct', 0):.0f}%")
    
    if results.get("buy_pct", 50) > 80:
        score += 15
        flags.append(f"BUY_HEAVY_{results['buy_pct']:.0f}%")
    
    if results.get("unique_wallets", 0) < 10 and results.get("total_trades", 0) > 20:
        score += 15
        flags.append("FEW_WALLETS")
    
    results["wash_score"] = score
    results["flags"] = flags
    results["verdict"] = "LIKELY_BOT" if score >= 50 else "MIXED" if score >= 25 else "ORGANIC"
    
    return results

def main():
    print(f"\n{'='*100}")
    print(f"PUMP.FUN MOVERS DEEP ANALYSIS - {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"Detecting wash trading, bots, and coordination patterns")
    print(f"{'='*100}\n")
    
    tokens = fetch_movers()
    print(f"Total movers fetched: {len(tokens)}\n")
    
    if not tokens:
        print("Failed to fetch movers!")
        return
    
    # Collect stats
    likely_bots = []
    organic = []
    mixed = []
    
    low_mc_tokens = []  # $3k-$10k range
    
    for i, token in enumerate(tokens[:20]):
        name = token.get('name', 'Unknown')[:30]
        symbol = token.get('symbol', '?')
        mint = token.get('mint', '')
        usd_mc = token.get('usd_market_cap', 0)
        mc_sol = token.get('market_cap', 0)
        replies = token.get('reply_count', 0)
        ath_mc = token.get('ath_market_cap', 0)
        trend_reason = token.get('trend_reason', '')[:50]
        created = token.get('created_timestamp', 0)
        
        # Calculate age
        age_hours = 0
        if created:
            age_hours = (datetime.now().timestamp() * 1000 - created) / (1000 * 60 * 60)
        
        print(f"\n{'-'*100}")
        print(f"#{i+1} {symbol} | ${usd_mc:,.0f} MC | {replies} replies | {age_hours:.0f}h old")
        print(f"    Name: {name}")
        print(f"    Mint: {mint[:40]}...")
        print(f"    ATH: ${ath_mc:,.0f} | Trend: {trend_reason}")
        
        # Track low MC tokens
        if 3000 <= usd_mc <= 15000:
            low_mc_tokens.append({
                'symbol': symbol,
                'usd_mc': usd_mc,
                'replies': replies,
                'age_hours': age_hours
            })
        
        # Fetch and analyze trades
        if mint:
            print(f"    Fetching trades...")
            trades = fetch_token_trades(mint)
            
            if trades:
                analysis = analyze_trade_patterns(trades, symbol)
                
                print(f"    Trades: {analysis.get('total_trades', 0)} | Unique: {analysis.get('unique_wallets', 0)} wallets")
                print(f"    Top Wallet: {analysis.get('top_wallet', '?')} ({analysis.get('top_wallet_pct', 0):.0f}% of trades)")
                print(f"    Repeat Traders: {analysis.get('repeat_traders', 0)} ({analysis.get('repeat_trader_pct', 0):.0f}%)")
                print(f"    Buy Ratio: {analysis.get('buy_pct', 50):.0f}%")
                
                if analysis.get('common_amount'):
                    print(f"    Common Amount: {analysis['common_amount']} SOL ({analysis.get('common_amount_count', 0)}x = {analysis.get('amount_repetition_pct', 0):.0f}%)")
                
                verdict = analysis.get('verdict', 'UNKNOWN')
                score = analysis.get('wash_score', 0)
                flags = ', '.join(analysis.get('flags', []))
                
                if verdict == "LIKELY_BOT":
                    print(f"    >>> VERDICT: BOT/WASH (Score: {score}/100) - {flags}")
                    likely_bots.append(symbol)
                elif verdict == "MIXED":
                    print(f"    >>> VERDICT: MIXED (Score: {score}/100) - {flags}")
                    mixed.append(symbol)
                else:
                    print(f"    >>> VERDICT: ORGANIC (Score: {score}/100)")
                    organic.append(symbol)
            else:
                print(f"    [No trade data available]")
        
        time.sleep(0.3)
    
    # SUMMARY
    print(f"\n{'='*100}")
    print("SUMMARY: MOVERS TAB COMPOSITION")
    print(f"{'='*100}")
    
    total = len(likely_bots) + len(mixed) + len(organic)
    if total > 0:
        print(f"LIKELY BOT/WASH: {len(likely_bots)} ({len(likely_bots)/total*100:.0f}%) - {', '.join(likely_bots[:10])}")
        print(f"MIXED SIGNALS:   {len(mixed)} ({len(mixed)/total*100:.0f}%) - {', '.join(mixed[:10])}")
        print(f"LIKELY ORGANIC:  {len(organic)} ({len(organic)/total*100:.0f}%) - {', '.join(organic[:10])}")
    
    print(f"\n{'='*100}")
    print("LOW MC MOVERS ($3k-$15k) - YOUR TARGET ZONE")
    print(f"{'='*100}")
    
    if low_mc_tokens:
        for t in low_mc_tokens:
            print(f"  {t['symbol']:12} | ${t['usd_mc']:,.0f} | {t['replies']} replies | {t['age_hours']:.0f}h old")
    else:
        print("  No tokens in $3k-$15k range on movers currently")
        print("  INSIGHT: Movers tab appears to favor higher MC tokens")
    
    # KEY INSIGHTS
    print(f"\n{'='*100}")
    print("KEY INSIGHTS FOR YOUR LAUNCHES")
    print(f"{'='*100}")
    print("Based on this analysis:")
    print("1. Check BOT PERCENTAGE above - if high, volume simulation WORKS")
    print("2. Low MC tokens may need MORE replies/engagement to appear")
    print("3. ATH metric shows explosive potential of trending coins")
    print("4. Trade patterns reveal what 'looks organic' to snipers")

if __name__ == "__main__":
    main()
