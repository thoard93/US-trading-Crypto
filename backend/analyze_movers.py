"""
Analyze collected mover data from the trading database.
Shows: whale wallets, mover snapshots, and patterns.
"""
import sqlite3
import os
import sys
from datetime import datetime, timedelta

# Fix encoding issues on Windows
sys.stdout.reconfigure(encoding='utf-8')

# Path to the database
DB_PATH = os.path.join(os.path.dirname(__file__), 'trading_platform.db')

def analyze_movers():
    if not os.path.exists(DB_PATH):
        print(f"[X] Database not found at {DB_PATH}")
        return
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    print("=" * 60)
    print("[CHART] MOVER DATA ANALYSIS")
    print("=" * 60)
    
    # 1. Check what tables exist
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = [row[0] for row in cursor.fetchall()]
    print(f"\n[LIST] Tables in database: {', '.join(tables)}")
    
    # 2. Analyze mover_snapshots if it exists
    if 'mover_snapshots' in tables:
        print("\n" + "-" * 40)
        print("[FIRE] MOVER SNAPSHOTS")
        print("-" * 40)
        
        cursor.execute("SELECT COUNT(*) as total FROM mover_snapshots")
        total = cursor.fetchone()['total']
        print(f"Total snapshots: {total}")
        
        if total > 0:
            # Recent snapshots
            cursor.execute("""
                SELECT symbol, mint, mc_usd, unique_buyers, sol_volume, score, snapshot_at
                FROM mover_snapshots
                ORDER BY snapshot_at DESC
                LIMIT 20
            """)
            rows = cursor.fetchall()
            print(f"\nRecent {len(rows)} snapshots:")
            for row in rows:
                print(f"  {row['symbol'] or 'N/A':>10} | MC: ${row['mc_usd'] or 0:,.0f} | Buyers: {row['unique_buyers']} | Vol: {row['sol_volume']:.2f} SOL | Score: {row['score']:.1f}")
            
            # Top performers by score
            cursor.execute("""
                SELECT symbol, mint, MAX(score) as max_score, AVG(mc_usd) as avg_mc, COUNT(*) as snapshots
                FROM mover_snapshots
                WHERE snapshot_at > datetime('now', '-1 day')
                GROUP BY mint
                ORDER BY max_score DESC
                LIMIT 10
            """)
            rows = cursor.fetchall()
            if rows:
                print(f"\n[TROPHY] Top 10 by Score (last 24h):")
                for row in rows:
                    print(f"  {row['symbol'] or row['mint'][:8]:>12} | Score: {row['max_score']:.1f} | Avg MC: ${row['avg_mc'] or 0:,.0f} | Snapshots: {row['snapshots']}")
    else:
        print("\n[!] mover_snapshots table not found")
    
    # 3. Analyze whale_wallets if it exists
    if 'whale_wallets' in tables:
        print("\n" + "-" * 40)
        print("[WHALE] WHALE WALLETS")
        print("-" * 40)
        
        cursor.execute("SELECT COUNT(*) as total FROM whale_wallets")
        total = cursor.fetchone()['total']
        print(f"Total whale wallets tracked: {total}")
        
        if total > 0:
            cursor.execute("""
                SELECT address, score, discovered_on, discovered_at, last_active
                FROM whale_wallets
                ORDER BY score DESC, last_active DESC
                LIMIT 15
            """)
            rows = cursor.fetchall()
            print(f"\nTop {len(rows)} whale wallets:")
            for row in rows:
                print(f"  {row['address'][:8]}...{row['address'][-4:]} | Score: {row['score']:.1f} | Found on: {row['discovered_on'] or 'N/A'} | Active: {row['last_active']}")
    else:
        print("\n[!] whale_wallets table not found")
    
    # 4. Analyze launched_keywords
    if 'launched_keywords' in tables:
        print("\n" + "-" * 40)
        print("[ROCKET] LAUNCHED KEYWORDS")
        print("-" * 40)
        
        cursor.execute("SELECT COUNT(*) as total FROM launched_keywords")
        total = cursor.fetchone()['total']
        print(f"Total keywords launched: {total}")
        
        if total > 0:
            cursor.execute("""
                SELECT keyword, name, symbol, mint_address, launched_at
                FROM launched_keywords
                ORDER BY launched_at DESC
                LIMIT 15
            """)
            rows = cursor.fetchall()
            print(f"\nRecent {len(rows)} launches:")
            for row in rows:
                print(f"  {row['keyword']:>15} -> {row['symbol'] or 'N/A':>8} | {row['launched_at']}")
    else:
        print("\n[!] launched_keywords table not found")
    
    # 5. Check dex_positions
    if 'dex_positions' in tables:
        print("\n" + "-" * 40)
        print("[MONEY] DEX POSITIONS")
        print("-" * 40)
        
        cursor.execute("SELECT COUNT(*) as total FROM dex_positions")
        total = cursor.fetchone()['total']
        print(f"Total positions: {total}")
        
        if total > 0:
            cursor.execute("""
                SELECT symbol, token_address, wallet_address, entry_price_usd, amount, timestamp
                FROM dex_positions
                ORDER BY timestamp DESC
                LIMIT 10
            """)
            rows = cursor.fetchall()
            print(f"\nRecent {len(rows)} positions:")
            for row in rows:
                print(f"  {row['symbol'] or 'N/A':>10} | Entry: ${row['entry_price_usd']:.6f} | Amt: {row['amount']:.0f} | {row['timestamp']}")
    else:
        print("\n[!] dex_positions table not found")
    
    conn.close()
    print("\n" + "=" * 60)
    print("Analysis complete!")

if __name__ == "__main__":
    analyze_movers()
