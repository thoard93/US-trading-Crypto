import json
import os
from datetime import datetime
from collections import defaultdict

def analyze_performance():
    log_path = os.path.join(os.path.dirname(__file__), 'data', 'trading_signals.jsonl')
    if not os.path.exists(log_path):
        print("No trading signals logged yet.")
        return

    stats = {
        "total_signals": 0,
        "decisions": defaultdict(int),
        "reasons": defaultdict(int),
        "avg_liquidity_skipped": [],
        "avg_confidence_skipped": [],
        "potential_buys_if_100k_liq": 0,
        "potential_buys_if_35_conf": 0
    }

    with open(log_path, 'r') as f:
        for line in f:
            try:
                data = json.loads(line)
                stats["total_signals"] += 1
                decision = data.get("decision")
                stats["decisions"][decision] += 1
                
                reason = data.get("reason", "")
                if reason:
                    stats["reasons"][reason[:50]] += 1

                liquidity = data.get("liquidity_usd", 0)
                confidence = data.get("confidence_score", 0)

                if decision == "SKIP_FILTER" and "Liquidity" in data.get("reason", ""):
                    stats["avg_liquidity_skipped"].append(liquidity)
                    if liquidity >= 100000:
                        stats["potential_buys_if_100k_liq"] += 1
                
                if decision == "SKIP_CONFIDENCE":
                    stats["avg_confidence_skipped"].append(confidence)
                    if confidence >= 35:
                        stats["potential_buys_if_35_conf"] += 1
            except:
                continue

    print(f"\n--- AI META-LOOP PERFORMANCE REPORT ({datetime.now().strftime('%Y-%m-%d %H:%M')}) ---")
    print(f"Total Signals Processed: {stats['total_signals']}")
    
    print("\nDecision Breakdown:")
    for decision, count in stats["decisions"].items():
        print(f"  - {decision}: {count}")

    print("\nOptimization Analysis:")
    if stats["avg_liquidity_skipped"]:
        avg_liq = sum(stats["avg_liquidity_skipped"]) / len(stats["avg_liquidity_skipped"])
        print(f"  - Avg Liquidity of Skips: ${avg_liq:,.0f}")
        print(f"  - OPPORTUNITY: Lowering to $100k would have added {stats['potential_buys_if_100k_liq']} potential trades.")
    
    if stats["avg_confidence_skipped"]:
        avg_conf = sum(stats["avg_confidence_skipped"]) / len(stats["avg_confidence_skipped"])
        print(f"  - Avg Confidence of Skips: {avg_conf:.1f}")
        print(f"  - OPPORTUNITY: Lowering to 35 Score would have added {stats['potential_buys_if_35_conf']} potential trades.")

    print("\n--- END REPORT ---")

if __name__ == "__main__":
    analyze_performance()
