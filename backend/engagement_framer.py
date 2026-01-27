import random
import logging
import asyncio
from datetime import datetime

class EngagementFramer:
    """
    Handles automated 'engagement farming' for new token launches.
    Generates hype comments and manages posting schedule.
    """
    def __init__(self, dex_trader=None):
        self.logger = logging.getLogger(__name__)
        self.dex_trader = dex_trader
        
        # Templates and phrase pools for maximum variety
        self.subjects = ["gang", "fam", "team", "dev", "creator", "we", "boys", "community"]
        self.actions = ["cooking", "executing", "moving", "sending it", "building", "printing", "pumping"]
        self.adjectives = ["heavy", "hard", "comfy", "fast", "mint", "early", "clean", "massive"]
        self.objects = ["bags", "floor", "candles", "chart", "structure", "vibes", "alpha"]

        self.comment_templates = [
            "{subject} {action} {adjective}",
            "{subject} is {action} {adjective}",
            "this {object} looking {adjective} rn",
            "just gotta hit it right",
            "another one",
            "we just getting started fr",
            "solid {object} forming",
            "moon is programmed",
            "send it to millions",
            "this is the one",
            "don't sell your {object} early lol",
            "{object} is immaculate",
            "bullish af on this {subject}",
            "chart looking like a staircase",
            "who's selling? lol thanks for cheapies",
            "unhinged energy in this chat",
            "organic growth only",
            "whale just entered?",
            "pasting the chart everywhere",
            "let's cook"
        ]
        
        # Identity wrappers
        self.prefixes = ["", "", "yo ", "damn ", "holly ", "sheesh ", "lfg ", "actually ", ""]
        self.suffixes = ["", "", " !!", "...", " fr fr", " lfg", " lol", ""]

    def generate_random_comment(self):
        """Build a highly randomized hype comment using phrase pools."""
        base_template = random.choice(self.comment_templates)
        
        # Fill placeholders if they exist
        comment = base_template.format(
            subject=random.choice(self.subjects),
            action=random.choice(self.actions),
            adjective=random.choice(self.adjectives),
            object=random.choice(self.objects)
        )
        
        prefix = random.choice(self.prefixes)
        suffix = random.choice(self.suffixes)
        
        comment = f"{prefix}{comment}{suffix}".strip()
        # Randomize capitalization
        if random.random() > 0.7:
            comment = comment.upper()
        elif random.random() > 0.5:
            comment = comment.capitalize()
            
        return comment

    async def farm_engagement(self, mint_address, count=3, delay_range=(10, 60)):
        """
        Post multiple comments over time.
        PHASE 56: Distributed Social Proof.
        Each comment comes from a DIFFERENT support wallet.
        """
        if not self.dex_trader:
            self.logger.warning("DexTrader not provided to EngagementFramer")
            print("⚠️ Engagement Farming: DexTrader not provided!")
            return
            
        print(f"🌾 Starting engagement farming for {mint_address} ({count} comments)")
        self.logger.info(f"🌾 Starting engagement farming for {mint_address} ({count} comments)")
        
        # Determine wallets to use
        wallets_to_use = []
        if hasattr(self.dex_trader, 'wallet_manager'):
            wm = self.dex_trader.wallet_manager
            # Gather all support keys
            support_keys = wm.get_all_support_keys()
            if support_keys:
                # Randomize order and take 'count' (cycling if needed)
                random.shuffle(support_keys)
                for i in range(count):
                    wallets_to_use.append(support_keys[i % len(support_keys)])
            else:
                # Fallback to main only
                wallets_to_use = [wm.get_main_key()] * count
        else:
            # Legacy fallback
            wallets_to_use = [None] * count

        for i in range(count):
            comment = self.generate_random_comment()
            payer_key = wallets_to_use[i]
            payer_addr = "main" if not payer_key else f"{payer_key[:6]}..."
            
            print(f"💬 Posting comment {i+1}/{count} from {payer_addr}: '{comment}'")
            self.logger.info(f"💬 Posting comment {i+1}/{count} from {payer_addr}: '{comment}'")
            
            try:
                # Post via DexTrader
                result = await asyncio.to_thread(self.dex_trader.post_pump_comment, mint_address, comment, payer_key=payer_key)
                
                if result.get('success'):
                    print(f"✅ Comment {i+1} posted successfully!")
                    self.logger.info(f"✅ Comment posted successfully: {result.get('signature')}")
                else:
                    print(f"❌ Comment {i+1} failed: {result.get('error')}")
                    self.logger.error(f"❌ Failed to post comment: {result.get('error')}")
            except Exception as e:
                print(f"❌ Comment {i+1} exception: {e}")
                self.logger.error(f"Exception posting comment: {e}")
                
            # Random delay between comments
            if i < count - 1:
                wait_time = random.randint(*delay_range)
                self.logger.debug(f"⏳ Waiting {wait_time}s before next comment...")
                await asyncio.sleep(wait_time)


if __name__ == "__main__":
    # Test generation
    framer = EngagementFramer()
    for _ in range(5):
        print(f"Generated: {framer.generate_random_comment()}")
