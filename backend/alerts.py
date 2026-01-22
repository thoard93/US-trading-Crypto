import discord
import json
import os
from discord.ext import tasks, commands
import asyncio
import datetime

from collectors.crypto_collector import CryptoCollector
# from collectors.stock_collector import StockCollector  # Disabled: alpaca not used
# from analysis.technical_engine import TechnicalAnalysis  # Disabled: pandas_ta incompatible with Python 3.11
from trading_executive import TradingExecutive
from collectors.dex_scout import DexScout
from analysis.safety_checker import SafetyChecker
from database import SessionLocal
import models
from analysis.copy_trader import SmartCopyTrader

# Import Polymarket modules (optional - may not be installed)
try:
    from collectors.polymarket_collector import get_polymarket_collector
    from analysis.polymarket_trader import get_polymarket_trader
    POLYMARKET_ENABLED = True
except ImportError as e:
    print(f"⚠️ Polymarket disabled: {e}")
    POLYMARKET_ENABLED = False

# Import DEX trader for automated Solana trading
try:
    from dex_trader import DexTrader
    DEX_TRADING_ENABLED = True
except ImportError as e:
    print(f"⚠️ DEX Trading disabled: {e}")
    DEX_TRADING_ENABLED = False

# Import encryption if available
try:
    from encryption_utils import decrypt_key
except ImportError:
    decrypt_key = lambda x: x # Fallback if no encryption

class AlertSystem(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        from collectors.crypto_collector import CryptoCollector
        # Initialize collectors as None to safely defer loading
        self.crypto = None 
        self.stocks = None
        self.analyzer = None  # TechnicalAnalysis() disabled - pandas_ta incompatible with Python 3.11
        self.trader = None # Critical fix: Defer TradingExecutive which hangs
        self.dex_scout = DexScout()
        self.safety = SafetyChecker()
        self.copy_trader = SmartCopyTrader()
        self.processed_swarms = set() # Track processed swarm signals (mint + window_id)
        
        # Initialize Polymarket (Paper Mode by default)
        self.polymarket_collector = None
        self.polymarket_trader = None
        if POLYMARKET_ENABLED:
            self.polymarket_collector = get_polymarket_collector()
            self.polymarket_trader = get_polymarket_trader()
            print(f"🎲 Polymarket Copy-Trader initialized (PAPER MODE)")
        
        # =========== TRADER INITIALIZATION (Deferred to cog_load) ===========
        self.ready = False # STATUS FLAG: Cog is registered but data is loading in background
        self.dex_traders = []
        self.dex_trader = None
        self.kraken_traders = []
        self.alpaca_traders = []
        
        # Trading Configuration (Settings)
        self.dex_auto_trade = False
        self.dex_min_safety_score = 50
        self.dex_min_liquidity = 50000  # $50k min - increased for Alpha Hunter strategy

        self.dex_max_positions = 15
        
        # Ultimate Bot Configuration
        self.whale_confidence_threshold = 25 # Sum of whale scores
        self.trailing_stop_pnl_trigger = 20.0 # Activates at 20% profit
        self.trailing_stop_distance = 10.0 # Trails 10% behind ATH
        self.dev_shadow_enabled = True
        self.dynamic_sizing_enabled = True

        
        self.stock_auto_trade = False
        self.stock_trade_amount = 5.0
        self.stock_max_positions = 5
        self.stock_positions = {}

        
        # User defined watchlists
        self.majors_watchlist = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'BNB/USDT']
        self.memes_watchlist = ['PEPE/USDT', 'SHIB/USDT', 'DOGE/USDT', 'BONK/USDT', 'WIF/USDT']
        
        # Expanded DEX watchlist - Hot Solana memecoins for day trading
        self.dex_watchlist = [
            # Top Solana Memecoins
            {"chain": "solana", "address": "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263"},  # BONK
            {"chain": "solana", "address": "EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm"},  # WIF (dogwifhat)
            {"chain": "solana", "address": "7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2hr"},  # POPCAT
            {"chain": "solana", "address": "MEW1gQWJ3nEXg2qgERiKu7FAFj79PHvQVREQUzScPP5"},   # MEW
            {"chain": "solana", "address": "ukHH6c7mMyiWCf1b9pnWe25TSpkDDt3H5pQZgZ74J82"},   # BOME
            {"chain": "solana", "address": "7BgBvyjrZX1YKz4oh9mjb8ZScatkkwb8DzFx7LoiVkM3"},  # SLERF
            {"chain": "solana", "address": "A8C3xuqscfmyLrte3VmTqrAq8kgMASius9AFNANwpump"},  # FARTCOIN
            {"chain": "solana", "address": "Df6yfrKC8kZE3KNkrHERKzAetSxbrWeniQfyJY4Jpump"},  # AI16Z
            {"chain": "solana", "address": "8x5VqbHA8D7NkD52uNuS5nnt3PwA8pLD34ymskeSo2Wn"},  # ZEREBRO
            {"chain": "solana", "address": "HBoNJ5v8g71s2boRivrHnfSB5MVPLDHHyVjruPfhGkvL"},  # Purple Pepe
        ]
        # Expanded stock watchlist - mix of large, mid, and small caps
        self.stock_watchlist = [
            # Large Caps
            'AAPL', 'TSLA', 'NVDA', 'AMD', 'MSFT', 'META', 'AMZN', 'GOOGL',
            # Mid Caps / Growth
            'PLTR', 'SOFI', 'HOOD', 'COIN', 'RBLX', 'SNAP', 'PINS',
            # Smaller / Volatile
            'GME', 'AMC', 'BBBY', 'MARA', 'RIOT', 'SOUN', 'IONQ'
        ]
        
        # User defined channel IDs
        self.STOCKS_CHANNEL_ID = 1456078814567202960
        self.CRYPTO_CHANNEL_ID = 1456078864684945531
        self.MEMECOINS_CHANNEL_ID = 1456439911896060028
        
        self.trending_dex_gems = [] # Temporarily tracked trending gems
        self.restricted_assets = set() # Session-based blacklist for "Restricted Region" assets
        self.last_exit_times = {} # {symbol: timestamp} for wash trade prevention
        self.last_alert_times = {} # {symbol: timestamp} to prevent discord spam
        self.dex_exit_cooldowns = {} # {token_address: timestamp} - prevents re-buying after SL
        
        # ORPHAN GUARD: Retry queue for failed sells
        self.sell_retry_queue = []  # [{token_address, trader, reason, attempts, last_attempt, slippage_bps}]

        # Load failed tokens blacklist
        self._failed_tokens = {}
        self.load_failed_tokens()

        self.load_failed_tokens()
        
        # Note: Loops and Webhook setup moved to cog_load for speed

    async def run_sync(self, func, *args, **kwargs):
        """Helper to run a synchronous blocking function in a background thread."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: func(*args, **kwargs))

    async def _startup_sync(self):
        """Wait for bot to be ready and sync existing positions."""
        if not self.bot.is_ready():
            await self.bot.wait_until_ready()
        # print("📥 Bot ready. Synchronizing live positions from Kraken...")
        # self.trader.sync_positions()  # DISABLED - Kraken removed
        
        # Log DEX trading status
        if self.dex_trader and self.dex_trader.wallet_address:
            sol_balance = await self.run_sync(self.dex_trader.get_sol_balance)
            print(f"💰 DEX Wallet SOL Balance: {sol_balance:.4f} SOL")
        
        # Sync Stock positions from Alpaca - DISABLED (Alpaca removed)
        # if self.stocks and self.stocks.api:
        #     try:
        #         positions = self.stocks.api.list_positions()
        #         for pos in positions:
        #             symbol = pos.symbol
        #             self.stock_positions[symbol] = {
        #                 'qty': float(pos.qty),
        #                 'avg_entry_price': float(pos.avg_entry_price),
        #                 'market_value': float(pos.market_value)
        #             }
        #         print(f"📈 Synced {len(positions)} Alpaca positions: {list(self.stock_positions.keys())}")
        #         
        #         account = self.stocks.get_account()
        #         if account:
        #             print(f"💵 Alpaca - Cash: ${account['cash']:.2f}, Buying Power: ${account['buying_power']:.2f}")
        #     except Exception as e:
        #         print(f"⚠️ Failed to sync Alpaca: {e}")
        
        # 🚀 START BACKGROUND LOOPS (must be started explicitly!)
        if not self.auto_hunt_loop.is_running():
            self.auto_hunt_loop.start()
            print("🦈 Auto-Hunt Loop STARTED (every 30 min)")
        
        if not self.auto_prune_loop.is_running():
            self.auto_prune_loop.start()
            print("🧹 Auto-Prune Loop STARTED (every 4 hours)")
        
        # 🛡️ ORPHAN GUARD: Safety net for stuck positions
        if not self.orphan_guard.is_running():
            self.orphan_guard.start()
            print("🛡️ Orphan Guard Loop STARTED (every 60s)")
            
        # 💎 HANDS SYNC: Reconcile memory with blockchain every 5 min
        if not self.dex_sync_loop.is_running():
            self.dex_sync_loop.start()
            print("💎 Diamond Hands Sync Loop STARTED (every 5 min)")

        # ⚡ IMMEDIATE SYNC: Sync current positions on startup
        asyncio.create_task(self.sync_all_dex_positions())

    async def setup_helius_webhook(self):
        """Registers the bot's URL with Helius to receive whale activity."""
        import os
        webhook_url = os.getenv("HELIUS_WEBHOOK_URL")
        if not webhook_url:
            print("⚠️ HELIUS_WEBHOOK_URL not set. Webhooks will not be automated.")
            return

        # Ensure URL ends with the endpoint
        clean_url = webhook_url.rstrip('/')
        if not clean_url.endswith("/helius/webhook"):
            webhook_url = f"{clean_url}/helius/webhook"
        else:
            webhook_url = clean_url

        # Get whale addresses (Monitoring all qualified whales up to 500)
        sorted_whales = sorted(
            self.copy_trader.qualified_wallets.items(),
            key=lambda x: x[1].get('discovered_at', ''),
            reverse=True
        )
        whales = [w[0] for w in sorted_whales[:500]]
        
        # If no whales, use the bot's own wallet as a placeholder to ensure the URL is registered in Helius
        if not whales:
            print("⚠️ No whales tracked yet. Using bot wallet as placeholder for registration.")
            if self.dex_trader and self.dex_trader.wallet_address:
                whales = [self.dex_trader.wallet_address]
            else:
                # Last resort fallback (System address)
                whales = ["11111111111111111111111111111111"]

        print(f"📡 Registering Helius Webhook at {webhook_url} (Monitoring top {len(whales)} freshest whales)...")
        result = await self.run_sync(self.copy_trader.collector.upsert_helius_webhook, webhook_url, whales)
        
        if result:
            print(f"✅ Helius Webhook Setup SUCCESS: {result.get('webhookID', 'Unknown ID')}")
        else:
            print("❌ Helius Webhook Setup FAILED. Check your HELIUS_API_KEY.")



    def load_failed_tokens(self):
        try:
            with open('failed_tokens.json', 'r') as f:
                self._failed_tokens = json.load(f)
            print(f"🛑 Loaded {len(self._failed_tokens)} failed tokens from disk.")
        except:
            self._failed_tokens = {}

    def save_failed_tokens(self):
        try:
            with open('failed_tokens.json', 'w') as f:
                json.dump(self._failed_tokens, f)
        except Exception as e:
            print(f"⚠️ Failed to save token blacklist: {e}")

    def cog_unload(self):
        self.monitor_market.cancel()
        self.discovery_loop.cancel()
        self.kraken_discovery_loop.cancel()
        self.swarm_monitor.cancel()

    @tasks.loop(minutes=10)  # POSITION TRADER MODE: Was 2 min, now 10 min (reduce churning)
    async def monitor_market(self):
        if not self.ready:
            return
        if not self.bot.is_ready():
            await self.bot.wait_until_ready()

        channel_crypto = self.bot.get_channel(self.CRYPTO_CHANNEL_ID)
        channel_memes = self.bot.get_channel(self.MEMECOINS_CHANNEL_ID)
        channel_stocks = self.bot.get_channel(self.STOCKS_CHANNEL_ID)

        # 0. Monitor Active Positions for ALL KRAKEN USERS - DISABLED (Kraken removed)
        # for kraken_trader in self.kraken_traders:
        #     user_label = getattr(kraken_trader, 'user_id', 'Main')
        #     all_owned = list(kraken_trader.active_positions.keys())
        #     if all_owned:
        #         print(f"🛡️ Monitoring {len(all_owned)} Kraken positions for User {user_label}...")
        #         for symbol in all_owned:
        #             # Detect asset type based on symbol format
        #             a_type = "Stock" if "/" not in symbol else "Crypto"
        #             # Use the specific user's trader for exit checks
        #             original_trader = self.trader
        #             self.trader = kraken_trader  # Temporarily swap to check this user's positions
        #             if a_type == "Crypto" and channel_crypto:
        #                 await self._check_and_alert(symbol, channel_crypto, a_type)
        #             elif a_type == "Stock" and channel_stocks:
        #                 await self._check_and_alert(symbol, channel_stocks, a_type)
        #             self.trader = original_trader  # Restore

        # 1. Monitor Majors - DISABLED (Kraken removed)
        # print(f"Checking major crypto: {self.majors_watchlist}")
        # if channel_crypto:
        #     for symbol in self.majors_watchlist:
        #         if symbol not in self.restricted_assets:
        #             await self._check_and_alert(symbol, channel_crypto, "Crypto")

        # 2. Monitor Memes (on Kraken) - DISABLED (Kraken removed)
        # print(f"Checking memecoins: {self.memes_watchlist}")
        # if channel_memes:
        #     for symbol in self.memes_watchlist:
        #         if symbol not in self.restricted_assets:
        #             await self._check_and_alert(symbol, channel_memes, "Meme")



        # 3. Monitor Stocks - DISABLED (Alpaca removed)
        # print(f"Checking stock markets: {self.stock_watchlist}")
        # if channel_stocks:
        #     for symbol in self.stock_watchlist:
        #         # Skip restricted assets
        #         if symbol not in self.restricted_assets:
        #             await self._check_and_alert(symbol, channel_stocks, "Stock")
        #         await asyncio.sleep(1)

    async def sync_all_dex_positions(self):
        """Syncs on-chain positions for all traders, loading entry prices from DB."""
        if not hasattr(self, 'dex_traders') or not self.dex_traders: return

        print("🔄 Syncing DEX positions from blockchain...")
        
        # 1. Load persisted positions from database
        db_positions = {}  # {(wallet_address, token_address): DexPosition}
        try:
            db = SessionLocal()
            all_db_pos = db.query(models.DexPosition).all()
            for pos in all_db_pos:
                key = (pos.wallet_address, pos.token_address)
                db_positions[key] = pos
            print(f"📚 Loaded {len(db_positions)} persisted DEX positions from DB")
        except Exception as e:
            print(f"⚠️ Error loading DB positions: {e}")
        finally:
            db.close()
        
        for trader in self.dex_traders:
            try:
                # 2. Get raw on-chain tokens
                wallet_tokens = await self.run_sync(trader.get_all_tokens)
                if not wallet_tokens: continue

                user_label = getattr(trader, 'user_id', 'Main')
                print(f"💰 Found {len(wallet_tokens)} existing tokens in wallet.")
                
                for mint, amount in wallet_tokens.items():
                    if mint in trader.positions: continue
                    
                    try:
                        # Check database for persisted entry price
                        db_key = (trader.wallet_address, mint)
                        db_pos = db_positions.get(db_key)
                        
                        # Map input for DexScout
                        pair_data = await self.dex_scout.get_pair_data('solana', mint)
                        if pair_data:
                            info = self.dex_scout.extract_token_info(pair_data)
                            current_price = info.get('price_usd')
                            symbol = info.get('symbol', 'UNKNOWN')
                            
                            if current_price:
                                # Use DB entry price if available, else fall back to current (legacy)
                                if db_pos:
                                    entry_price = db_pos.entry_price_usd
                                    print(f"🔓 Restored {symbol} for User {user_label} @ ${entry_price:.6f} (from DB)")
                                else:
                                    entry_price = current_price
                                    print(f"✅ Adopted {symbol} for User {user_label} @ ${entry_price:.6f} (NEW)")
                                
                                trader.positions[mint] = {
                                    'entry_price_usd': entry_price,
                                    'amount': amount,
                                    'symbol': symbol,
                                    'highest_pnl': db_pos.highest_pnl if db_pos else 0.0,
                                    'entry_time': db_pos.timestamp.timestamp() if db_pos else datetime.datetime.now().timestamp()
                                }
                                
                                # --- SWARM HEALING (NEW) ---
                                # Check if we have swarm participants for this token.
                                # If not, try to 'heal' by searching whale history.
                                if mint not in self.copy_trader.active_swarms:
                                    participants = await self.copy_trader.search_participants_for_token(mint)
                                    if participants:
                                        self.copy_trader.active_swarms[mint] = participants
                                        # Persist to DB so it survives future restarts too
                                        for p in participants:
                                            self.copy_trader._save_swarm_participant(mint, p)
                                        print(f"🩹 Position Healed: Restored {len(participants)} whales for {symbol}")
                                
                                # Add to tracking list if not there
                                found = False
                                for t in self.trending_dex_gems:
                                    if t['address'] == mint: found = True
                                if not found:
                                     self.trending_dex_gems.append({
                                         'chain': 'solana', 'address': mint, 'symbol': symbol
                                     })
                                
                    except Exception as e:
                        print(f"⚠️ Failed to adopt token {mint}: {e}")
                
                # 3. Cleanup: Remove positions NOT in wallet (Manual Sells)
                current_mints = list(wallet_tokens.keys())
                to_remove = []
                for mint in trader.positions.keys():
                    if mint not in current_mints:
                        to_remove.append(mint)
                
                for mint in to_remove:
                    print(f"🧹 Detecting manual sell for {trader.positions[mint].get('symbol', 'Unknown')}. Clearing from memory/DB.")
                    del trader.positions[mint]
                    # Clean DB
                    try:
                        db = SessionLocal()
                        db.query(models.DexPosition).filter(
                            models.DexPosition.wallet_address == trader.wallet_address,
                            models.DexPosition.token_address == mint
                        ).delete()
                        db.commit()
                        db.close()
                    except: pass

            except Exception as e:
                print(f"❌ Error syncing user {user_label}: {e}")

    @tasks.loop(minutes=3)  # POSITION TRADER MODE: Was 15s, now 3 min (stop churning)
    async def dex_monitor(self):
        """Dedicated high-speed loop for DEX memecoins (30s)."""
        # Add jitter to prevent API storms from multiple instances
        import random
        await asyncio.sleep(random.randint(1, 15))
        
        if not self.ready:
            return
        if not self.bot.is_ready():
            return
            
        # Sync on first run
        if not hasattr(self, 'dex_positions_synced'):
             await self.sync_all_dex_positions()
             self.dex_positions_synced = True

        channel_memes = self.bot.get_channel(self.MEMECOINS_CHANNEL_ID)
        
        # --- SOL LOW BALANCE ALERT (every loop) ---
        for trader in self.dex_traders:
            sol_bal = await self.run_sync(trader.get_sol_balance)
            if sol_bal < 0.05:  # Refined threshold: 0.05 SOL
                user_label = getattr(trader, 'user_id', 'Main')
                # Alert cooldown: 1 hour per user
                cooldown_key = f"bal_alert_{user_label}"
                last_alert = getattr(self, cooldown_key, 0)
                if datetime.datetime.now().timestamp() - last_alert > 3600:
                    setattr(self, cooldown_key, datetime.datetime.now().timestamp())
                    addr = trader.wallet_address[:8] + "..." + trader.wallet_address[-4:]
                    if channel_memes:
                        await channel_memes.send(
                            f"🛑 **CRITICAL LOW SOL ALERT** | User {user_label}\n"
                            f"Balance: `{sol_bal:.4f} SOL` (< 0.05 SOL)\n"
                            f"Wallet: `{addr}`\n"
                            f"Top up IMMEDIATELY to continue trading and landed exits!"
                        )
        
        # Monitor DEX Scout (New Gems) + Auto-Trade
        # print(f"⚡ DEX Monitor: Scouting {len(self.dex_watchlist)} tokens...")
        if channel_memes:
            # 1. Collect all tokens to monitor: Watchlist + Trending + HELD POSITIONS
            held_tokens = []
            if self.dex_traders:
                for trader in self.dex_traders:
                    for token_addr, data in trader.positions.items():
                        held_tokens.append({'address': token_addr, 'symbol': data.get('symbol', 'UNKNOWN'), 'chain': 'solana'})
            
            # Combine unique by address
            all_dex_map = {}
            for item in self.dex_watchlist + self.trending_dex_gems + held_tokens:
                all_dex_map[item['address']] = item
            
            all_dex = list(all_dex_map.values())

            for item in all_dex:
                try:
                    pair_data = await self.dex_scout.get_pair_data(item['chain'], item['address'])
                    if pair_data:
                        info = self.dex_scout.extract_token_info(pair_data)
                        token_address = info.get('address', item['address'])
                        
                        # Alert if price change > 1% in 5 minutes (SNIPER MODE)
                        if info['price_change_5m'] >= 1.0:
                            # Safety Audit
                            audit = await self.safety.check_token(token_address, "solana" if info['chain'] == 'solana' else "1")
                            safety_score = audit.get('safety_score', 0)
                            liquidity = info.get('liquidity_usd', 0)
                            
                            color = discord.Color.purple()
                            embed = discord.Embed(
                                title=f"🚀 DEX GEM PUMPING: {info['symbol']} ({info['chain'].upper()})", 
                                color=color
                            )
                            
                            if liquidity < 5000:
                                embed.add_field(name="⚠️ LOW LIQUIDITY", value=f"${liquidity:,.0f} - High Slippage Risk!", inline=False)
                            embed.add_field(name="Price USD", value=f"${info['price_usd']:.8f}", inline=True)
                            embed.add_field(name="5m Change", value=f"+{info['price_change_5m']}%", inline=True)
                            embed.add_field(name="Liquidity", value=f"${liquidity:,.0f}", inline=True)
                            embed.add_field(name="Safety Score", value=f"**{safety_score}/100**", inline=True)
                            
                            trade_happened = False
                            
                            if info['chain'] != 'solana':
                                embed.set_footer(text=f"ℹ️ Auto-Trade Skipped: {info['chain'].upper()} not supported (Solana Only)")

                            # AUTO-TRADE logic (Multi-User)
                            if (self.dex_auto_trade and 
                                self.dex_traders and 
                                info['chain'] == 'solana'):
                                
                                # CHECK COOLDOWN: Skip if recently sold this token
                                cooldown_time = self.dex_exit_cooldowns.get(token_address, 0)
                                if datetime.datetime.now().timestamp() - cooldown_time < 300: # 5 min cooldown
                                    continue  # Skip this token
                                
                                if safety_score >= self.dex_min_safety_score and liquidity >= self.dex_min_liquidity:
                                    
                                    # --- CONVICTION SIZING (NEW) ---
                                    # High-conviction = 2x position for vetted tokens
                                    is_high_conviction = (safety_score >= 80 and liquidity >= 50000)
                                    dex_trade_amount = 0.10 if is_high_conviction else 0.05  # SOL
                                    conviction_label = "🔥 HIGH CONVICTION" if is_high_conviction else ""
                                    
                                    # Execute for EACH trader
                                    for trader in self.dex_traders:
                                        dex_positions = len(trader.positions)
                                        
                                        if dex_positions < self.dex_max_positions:
                                            if token_address not in trader.positions:
                                                trade_result = trader.buy_token(token_address, sol_amount=dex_trade_amount)
                                                
                                                user_label = getattr(trader, 'user_id', 'Main')
                                                
                                                if trade_result.get('success'):
                                                    # Record entry price for PnL tracking
                                                    entry_price = info['price_usd']
                                                    trader.positions[token_address]['entry_price_usd'] = entry_price
                                                    trader.positions[token_address]['symbol'] = info['symbol']
                                                    trader.positions[token_address]['entry_time'] = datetime.datetime.now().timestamp()
                                                    trader.positions[token_address]['highest_price_usd'] = entry_price
                                                    
                                                    # PERSIST TO DATABASE (Critical for SL/TP across restarts)
                                                    try:
                                                        db = SessionLocal()
                                                        token_amt = trader.positions[token_address].get('tokens_received', 0)
                                                        new_dex_pos = models.DexPosition(
                                                            token_address=token_address,
                                                            wallet_address=trader.wallet_address,
                                                            symbol=info['symbol'],
                                                            entry_price_usd=entry_price,
                                                            amount=float(token_amt)
                                                        )
                                                        db.add(new_dex_pos)
                                                        db.commit()
                                                        print(f"💾 Persisted DEX position {info['symbol']} @ ${entry_price:.8f}")
                                                    except Exception as db_err:
                                                        print(f"⚠️ DB persist error: {db_err}")
                                                    finally:
                                                        db.close()
                                                    
                                                    trade_happened = True
                                                    embed.add_field(
                                                        name=f"🤖 BOUGHT (User {user_label})", 
                                                        value=f"TX: `{trade_result['signature'][:15]}...`", 
                                                        inline=False
                                                    )
                                                    embed.color = discord.Color.green()
                                                else:
                                                    embed.add_field(name=f"⚠️ Failed (User {user_label})", value=trade_result.get('error', 'Unknown'), inline=False)
                                                    # ADD FAILED BUY COOLDOWN: Don't retry for 10 mins
                                                    self.dex_exit_cooldowns[token_address] = datetime.datetime.now().timestamp()
                                        else:
                                            # Already holding
                                            pass
                                else:
                                    # LOG REJECTION: Low Liquidity or Safety
                                    reason = []
                                    if liquidity < self.dex_min_liquidity:
                                        reason.append(f"Liq ${liquidity:,.0f} < ${self.dex_min_liquidity:,.0f}")
                                    if safety_score < self.dex_min_safety_score:
                                        reason.append(f"Safety {safety_score} < {self.dex_min_safety_score}")
                                    print(f"🚫 Skipped {info['symbol']}: {', '.join(reason)}")
                            
                            # Smart Alerting: Only send if trade happened OR cooldown passed (10 mins)
                            should_send = False
                            now = datetime.datetime.now().timestamp()
                            last_sent = self.last_alert_times.get(token_address, 0)
                            
                            if trade_happened:
                                should_send = True
                            elif (now - last_sent) > 600: # 10 mins
                                should_send = True
                                
                            if should_send:
                                embed.add_field(name="DEX Link", value=f"[View on DexScreener]({info['url']})", inline=False)
                                await channel_memes.send(embed=embed)
                                self.last_alert_times[token_address] = now
                        
                        # EXIT LOGIC (Multi-User - ALWAYS CHECK)
                        if self.dex_traders and info['chain'] == 'solana':
                            for trader in self.dex_traders:
                                if token_address in trader.positions:
                                    pos = trader.positions[token_address]
                                    entry_price = pos.get('entry_price_usd')
                                    should_sell = False
                                    reason = ""
                                    user_label = getattr(trader, 'user_id', 'Main')
                                    
                                    # --- LEGACY POSITION CLEANUP (DISABLED) ---
                                    # This was causing all positions to sell on restart
                                    # Now we keep positions until they hit exit conditions
                                    # if not pos.get('entry_time'):
                                    #     pnl = 0
                                    #     if entry_price and info['price_usd']:
                                    #         pnl = ((info['price_usd'] - entry_price) / entry_price) * 100
                                    #     should_sell = True
                                    #     reason = f"🧹 Legacy Cleanup (No entry_time, P&L: {pnl:+.1f}%)"
                                    #     print(f"🧹 Cleaning legacy position: {info['symbol']} (User {user_label})")
                                    
                                    if entry_price:
                                        pnl = ((info['price_usd'] - entry_price) / entry_price) * 100
                                        
                                        # Status Pulse (Approx every ~5 mins if loop is 15s)
                                        # Status Pulse (Approx every ~5 mins)
                                        if not hasattr(self, 'pnl_tick'): self.pnl_tick = 0
                                        self.pnl_tick += 1
                                        if self.pnl_tick % 40 == 0: 
                                            print(f"👀 Status {info['symbol']} (User {user_label}): {pnl:+.2f}% (TP: +25 | SL: -25)")

                                        # PARTIAL PROFIT: At +25%, sell 50% and let rest ride
                                        partial_sold = pos.get('partial_sold', False)
                                        if pnl >= 25.0 and not partial_sold:
                                            # Sell 50% (partial)
                                            res = trader.sell_token(token_address, percentage=50)
                                            if res.get('success'):
                                                pos['partial_sold'] = True
                                                await channel_memes.send(f"🎯 **Partial TP (+{pnl:.1f}%)**: USER {user_label} Sold 50% of {info['symbol']}")
                                        
                                        # FULL EXIT: +50% OR trailing (moonbag capture)
                                        if pnl >= 50.0:
                                            should_sell = True
                                            reason = f"🌙 Moonbag Exit (+{pnl:.1f}%)"
                                        
                                        # --- DEX TRAILING STOP (NEW) ---
                                        # Update high water mark
                                        current_price = info['price_usd']
                                        if 'highest_price_usd' not in pos:
                                            pos['highest_price_usd'] = entry_price
                                        if current_price > pos['highest_price_usd']:
                                            pos['highest_price_usd'] = current_price
                                        
                                        # Trigger trailing stop if +10% reached
                                        if pnl >= 10.0 and not should_sell:
                                            peak = pos['highest_price_usd']
                                            drawdown = ((peak - current_price) / peak) * 100
                                            if drawdown >= 5.0:  # 5% drop from peak
                                                locked_gain = ((current_price - entry_price) / entry_price) * 100
                                                should_sell = True
                                                reason = f"📉 Trailing Stop (Locked +{locked_gain:.1f}% from +{pnl:.1f}% peak)"
                                        
                                        # --- STOP LOSS & FAST FAIL (Alpha Hunter) ---
                                        if not should_sell:
                                            if pnl <= -25.0:
                                                should_sell = True
                                                reason = f"🛑 Stop Loss ({pnl:.1f}%)"
                                            elif pnl <= -15.0:
                                                entry_time = pos.get('entry_time', 0)
                                                if entry_time:
                                                    minutes_held = (datetime.datetime.now().timestamp() - entry_time) / 60
                                                    if minutes_held >= 5.0:
                                                        should_sell = True
                                                        reason = f"⚡ Fast-Fail Exit: {pnl:.1f}% after {minutes_held:.1f}m"
                                        
                                        # --- TIME-BASED EXIT (NEW) ---
                                        entry_time = pos.get('entry_time', 0)
                                        if entry_time and not should_sell:
                                            hours_held = (datetime.datetime.now().timestamp() - entry_time) / 3600
                                            if hours_held >= 3.0:
                                                if pnl > 0:
                                                    should_sell = True
                                                    reason = f"⏰ Time Exit: +{pnl:.1f}% after {hours_held:.1f}h (take profit)"
                                                elif pnl <= -10.0:
                                                    should_sell = True
                                                    reason = f"⏰ Time Exit: {pnl:.1f}% after {hours_held:.1f}h (cut loser)"
                                        
                                        # --- SWARM DUMP EXIT (Smart Copy) ---
                                        # DISABLED: Now using webhook-based instant exits (detect_whale_sells)
                                        # This polling method is redundant and wastes Helius API credits
                                        # elif not should_sell:
                                        #     is_swarm_dump = await self.copy_trader.check_swarm_exit(token_address)
                                        #     if is_swarm_dump:
                                        #         should_sell = True
                                        #         reason = f"📉 Swarm Dump (Whales exiting)"

                                        # PSYCHOLOGICAL RESISTANCE EXITS (Research Phase 9)
                                        mc = info.get('market_cap', 0)
                                        if not should_sell and pnl > 5.0: 
                                            if 95000 <= mc <= 105000:
                                                should_sell = True
                                                reason = f"🧠 Psych Exit: 100k MC Wall ({pnl:.1f}%)"
                                            elif 480000 <= mc <= 520000:
                                                should_sell = True
                                                reason = f"🧠 Psych Exit: 500k MC Wall ({pnl:.1f}%)"
                                            elif 950000 <= mc <= 1050000:
                                                should_sell = True
                                                reason = f"🧠 Psych Exit: 1M MC Wall ({pnl:.1f}%)"

                                        # --- GARBAGE COLLECTION (Bag Holding Fix) ---
                                        # 1. Liquidity Death Check
                                        current_liq = info.get('liquidity_usd', 0)
                                        if current_liq < 3000:
                                            should_sell = True
                                            reason = f"☠️ Liquidity Death (${current_liq:,.0f} < $3k)"
                                        
                                        # 2. Safety Degradation Check (Audit occasionally)
                                        # Only check every ~5 mins (synced with status pulse) to save API credits
                                        if not should_sell and self.pnl_tick % 20 == 0:
                                            latest_audit = await self.safety.check_token(token_address, "solana")
                                            current_score = latest_audit.get('safety_score', 100)
                                            if current_score < 40:
                                                should_sell = True
                                                reason = f"🛡️ Safety Critical: Score Dropped to {current_score}"
                                    
                                    # Fallback dump check
                                    if not should_sell and info['price_change_5m'] <= -30.0:
                                        should_sell = True
                                        reason = f"🚨 Crash Detected (-30% in 5m)"
                                        
                                    if should_sell:
                                        res = trader.sell_token(token_address)
                                        if res.get('success'):
                                            await channel_memes.send(f"{reason}: USER {user_label} Sold {info['symbol']}")
                                            
                                            # SET COOLDOWN: Prevent re-buying for 5 minutes
                                            self.dex_exit_cooldowns[token_address] = datetime.datetime.now().timestamp()
                                            
                                            # DELETE FROM DATABASE
                                            try:
                                                db = SessionLocal()
                                                db.query(models.DexPosition).filter(
                                                    models.DexPosition.wallet_address == trader.wallet_address,
                                                    models.DexPosition.token_address == token_address
                                                ).delete()
                                                db.commit()
                                                print(f"🗑️ Removed DEX position {info['symbol']} from DB")
                                            except Exception as db_err:
                                                print(f"⚠️ DB delete error: {db_err}")
                                            finally:
                                                db.close()
                                        else:
                                            error_msg = res.get('error', '')
                                            print(f"⚠️ Sell failed for {info['symbol']}: {error_msg}")
                                            
                                            # GHOST POSITION CLEANUP: Remove from memory if no tokens on-chain
                                            if 'No tokens to sell' in str(error_msg):
                                                if token_address in trader.positions:
                                                    del trader.positions[token_address]
                                                    print(f"👻 Cleared ghost position {info['symbol']} from memory")
                                                # Also remove from DB
                                                try:
                                                    db = SessionLocal()
                                                    db.query(models.DexPosition).filter(
                                                        models.DexPosition.wallet_address == trader.wallet_address,
                                                        models.DexPosition.token_address == token_address
                                                    ).delete()
                                                    db.commit()
                                                except Exception:
                                                    pass
                                                finally:
                                                    db.close()

                except Exception as ex:
                    print(f"⚠️ Error checking DEX token {item.get('address')}: {ex}")
                
                await asyncio.sleep(0.5)

    @tasks.loop(minutes=10)  # POSITION TRADER MODE: Was 2 min, now 10 min
    async def discovery_loop(self):
        """Find new trending DEX gems automatically - SNIPER MODE."""
        # Add jitter to prevent API storms from multiple instances
        import random
        await asyncio.sleep(random.randint(5, 45))
        
        if not self.ready:
            return
        if not self.bot.is_ready(): return
        
        # COPY-TRADING ONLY MODE: Skip discovery when auto-trade is disabled
        if not self.dex_auto_trade:
            return  # Only trade via swarm copy-trading
        
        print("🔍 Running DEX Gem Discovery... (SNIPER MODE)")
        channel_memes = self.bot.get_channel(self.MEMECOINS_CHANNEL_ID)
        
        new_gems = []
        
        # 1. Fetch TRENDING Solana pairs (top pumpers)
        try:
            trending = await self.dex_scout.get_trending_solana_pairs(min_liquidity=self.dex_min_liquidity, limit=10)
            for pair in trending:
                addr = pair.get('baseToken', {}).get('address')
                if not addr:
                    continue
                    
                # Skip if already tracking
                if any(item['address'] == addr for item in self.dex_watchlist + self.trending_dex_gems):
                    continue
                
                # Check if pumping enough (1% in 5 min)
                change_5m = float(pair.get('priceChange', {}).get('m5', 0))
                liquidity = float(pair.get('liquidity', {}).get('usd', 0))
                
                if change_5m >= 1.0 and liquidity >= self.dex_min_liquidity:
                    # Quick safety check
                    audit = await self.safety.check_token(addr, "solana")
                    safety_score = audit.get('safety_score', 0)
                    
                if safety_score >= self.dex_min_safety_score:
                    new_gems.append({"chain": "solana", "address": addr})
                    
                    # ONLY send alerts if Auto-Trading is enabled (Sniper Mode)
                    # Prevents spamming "Gem Found" alerts during Copy-Trading only mode
                    if self.dex_auto_trade:
                        if channel_memes:
                            embed = discord.Embed(
                                title=f"🎯 SNIPER TARGET: {pair.get('baseToken', {}).get('symbol')}",
                                description=f"**+{change_5m:.1f}%** in 5min | Safety: {safety_score}/100",
                                color=discord.Color.gold()
                            )
                            embed.add_field(name="Price", value=f"${float(pair.get('priceUsd', 0)):.8f}", inline=True)
                            embed.add_field(name="Liquidity", value=f"${liquidity:,.0f}", inline=True)
                            
                            # IMMEDIATE SNIPE when discovery finds a good gem
                            if (self.dex_trader and 
                                self.dex_trader.wallet_address and
                                addr not in self.dex_trader.positions and
                                len(self.dex_trader.positions) < self.dex_max_positions):
                                
                                trade_result = self.dex_trader.buy_token(addr)
                                if trade_result.get('success'):
                                    embed.add_field(
                                        name="🤖 SNIPED!", 
                                        value=f"TX: `{trade_result['signature'][:16]}...`", 
                                        inline=False
                                    )
                                    embed.color = discord.Color.green()
                                else:
                                    embed.add_field(name="⚠️ Snipe Failed", value=trade_result.get('error', 'Unknown')[:100], inline=False)
                            
                            await channel_memes.send(embed=embed)
        except Exception as e:
            print(f"⚠️ Trending scan error: {e}")
        
        # 2. Fetch token profiles (original method)
        try:
            profiles = await self.dex_scout.get_latest_token_profiles()
            if profiles:
                for p in profiles[:5]:
                    addr = p.get('tokenAddress')
                    chain = p.get('chainId')
                    
                    if any(item['address'] == addr for item in self.dex_watchlist + self.trending_dex_gems + new_gems):
                        continue
                        
                    audit = await self.safety.check_token(addr, "solana" if chain == 'solana' else "1")
                    if audit.get('safety_score', 0) >= self.dex_min_safety_score:
                        new_gems.append({"chain": chain, "address": addr})
        except Exception as e:
            print(f"⚠️ Profile scan error: {e}")

        # Update trending gems (keep them for multiple cycles)
        self.trending_dex_gems = new_gems + self.trending_dex_gems[:15]
        print(f"📊 Tracking {len(self.trending_dex_gems)} trending gems")

    @tasks.loop(hours=1)
    async def kraken_discovery_loop(self):
        """Automatically find top volume cryptos on Kraken."""
        if not self.ready:
            return
        if not self.bot.is_ready(): return
        
        # DISABLED - Kraken removed from DEX-only mode
        return
        # print("🔍 Running Kraken Market Discovery...")
        try:
            # Load markets to ensure valid mapping
            markets = self.crypto.exchange.load_markets()
            
            # Fetch all tickers from Kraken
            tickers = self.crypto.exchange.fetch_tickers()
            usdt_tickers = []
            
            for symbol, ticker in tickers.items():
                # Filter for USDT pairs that are ACTUALLY tradable
                if '/USDT' in symbol and ticker.get('quoteVolume') and symbol in markets:
                    m = markets[symbol]
                    if m.get('active') and m.get('spot'):
                        usdt_tickers.append({
                            'symbol': symbol,
                            'volume': float(ticker.get('quoteVolume', 0)),
                            'price': float(ticker.get('last', 0))
                        })
            
            # Sort by volume (Top 30)
            sorted_tickers = sorted(usdt_tickers, key=lambda x: x['volume'], reverse=True)[:30]
            
            new_majors = []
            new_memes = []
            
            for t in sorted_tickers:
                s = t['symbol']
                p = t['price']
                
                # Exclude USDC/USDT and specific restricted pairs if we find them
                if 'USDC' in s or 'PYUSD' in s: continue
                
                # Exclude sub-pennies/memes from majors
                if p > 0.5 and s not in new_majors:
                    new_majors.append(s)
                elif p <= 0.5 and s not in new_memes:
                    new_memes.append(s)
            
            # Core pairs (that we know work or want anyway)
            core_majors = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'XRP/USDT', 'XMR/USDT', 'LINK/USDT']
            # VOLATILE MEMES - Focus on coins that MOVE (not slow majors!)
            core_memes = [
                'DOGE/USDT', 'SHIB/USDT', 'ADA/USDT',     # Classic memes
                'PENGU/USDT', 'FARTCOIN/USDT', 'MELANIA/USDT',  # New volatile memes
                'KAS/USDT', 'APE/USDT', 'MANA/USDT',      # Mid-cap volatile
                'ALGO/USDT', 'CC/USDT',                    # Lower cap movers
            ]
            
            self.majors_watchlist = sorted(list(set(core_majors + new_majors[:8])))
            self.memes_watchlist = sorted(list(set(core_memes + new_memes[:12])))
            
            print(f"✅ Kraken Watchlist Updated: Majors({len(self.majors_watchlist)}), Memes({len(self.memes_watchlist)})")
            
        except Exception as e:
            print(f"❌ Kraken Discovery error: {e}")

    @tasks.loop(minutes=30)
    async def auto_hunt_loop(self):
        """Automatically hunt for new DEX whales every 30 minutes."""
        # Add jitter to prevent API storms from multiple instances
        import random
        await asyncio.sleep(random.randint(10, 60))
        
        if not self.ready or not self.copy_trader:
            return
        if not self.bot.is_ready():
            return
        
        # Prevent concurrent hunts
        if hasattr(self, '_hunt_lock') and self._hunt_lock:
            return
        
        # 🛡️ Hunt Cooldown: Skip if we hunted in the last 10 minutes (prevents cold start burst)
        now = datetime.datetime.now().timestamp()
        last_hunt = getattr(self, '_last_hunt_time', 0)
        if now - last_hunt < 600:  # 10 minutes
            print("🦈 Auto-Hunt: Skipping (recently hunted)")
            return
        
        self._hunt_lock = True
        self._last_hunt_time = now
        try:
            print("🦈 Auto-Hunt: Scanning for new whales...")
            new_wallets = await asyncio.to_thread(
                self.copy_trader.scan_market_for_whales_sync, 
                max_pairs=15, 
                max_traders_per_pair=5
            )
            
            if new_wallets > 0:
                print(f"🐋 Auto-Hunt: Found {new_wallets} new whales! Updating Helius webhook...")
                await self.setup_helius_webhook()
                
                channel_memes = self.bot.get_channel(self.MEMECOINS_CHANNEL_ID)
                if channel_memes:
                    total = len(self.copy_trader.qualified_wallets)
                    await channel_memes.send(f"🦈 **Auto-Hunt Complete!** Found {new_wallets} new whales. Total: {total}")
            else:
                print("🦈 Auto-Hunt: No new qualified whales found this cycle.")
        except Exception as e:
            print(f"❌ Auto-Hunt error: {e}")
        finally:
            self._hunt_lock = False

    @tasks.loop(hours=4)
    async def auto_prune_loop(self):
        """Automatically prune lazy whales every 4 hours (12h inactivity threshold)."""
        if not self.ready or not self.copy_trader:
            return
        if not self.bot.is_ready():
            return
        
        print("🧹 Running auto-prune for lazy whales...")
        pruned = self.copy_trader.prune_lazy_whales(inactive_hours=12)
        
        if pruned > 0:
            channel_memes = self.bot.get_channel(self.MEMECOINS_CHANNEL_ID)
            if channel_memes:
                remaining = len(self.copy_trader.qualified_wallets)
                await channel_memes.send(f"🧹 **Auto-Pruned {pruned} lazy whales** (inactive > 12h). {remaining} active whales remaining.")

    @tasks.loop(minutes=5)
    async def dex_sync_loop(self):
        """Automatically reconcile on-chain positions with memory/DB every 5 minutes."""
        if not self.ready:
            return
        try:
            await self.sync_all_dex_positions()
        except Exception as e:
            print(f"❌ Error in dex_sync_loop: {e}")


    async def _check_and_alert(self, symbol, channel, asset_type):
        """Helper to fetch data, check exits, and process alerts."""
        try:
            # Use 5m timeframe for scalping/memes, 1h for stocks
            tf = '5m' if asset_type in ["Meme", "Crypto"] else '1h'
            
            # Use different collectors based on asset type
            if asset_type == "Stock":
                data = self.stocks.fetch_ohlcv(symbol, timeframe='1Hour', limit=100)
            else:
                data = self.crypto.fetch_ohlcv(symbol, timeframe=tf, limit=100)
            
            if data is None or data.empty:
                return

            current_price = data.iloc[-1]['close']
            p_str = f"{current_price:.8f}" if current_price < 1.0 else f"{current_price:.2f}"
            
            # Stop-Loss / Take-Profit (Only if we have a position)
            if symbol in self.trader.active_positions:
                exit_reason = self.trader.check_exit_conditions(symbol, current_price)
                if exit_reason:
                    if asset_type == "Stock":
                        exit_res = self.trader.execute_market_sell_stock(symbol)
                    else:
                        exit_res = self.trader.execute_market_sell(symbol)

                    if "error" not in exit_res:
                        embed = discord.Embed(
                            title=f"🚨 AUTO-EXIT ({asset_type.upper()}): {exit_reason}",
                            description=f"Closed position for **{symbol}** at ${p_str}",
                            color=discord.Color.orange()
                        )
                        await channel.send(embed=embed)
                        if symbol in self.trader.active_positions:
                            del self.trader.active_positions[symbol]
                            # Clean up stock specific tracking
                            if symbol in self.stock_positions:
                                del self.stock_positions[symbol]
                        
                        # Record exit time for cooldown
                        self.last_exit_times[symbol] = datetime.datetime.now()
                        
                        # CRITICAL: Return here to prevent the bot from immediately re-buying
                        # if the trend analysis still says 'BUY'
                        print(f"🛑 Position exited for {symbol}. Cooldown started. Skipping further analysis.")
                        return 
                    else:
                        # Handle specific sell errors (e.g., Ghost positions)
                        err_msg = str(exit_res.get('error', '')).lower()
                        if "insufficient qty" in err_msg or "not found" in err_msg:
                            print(f"⚠️ Ghost position detected for {symbol}. Clearing local state.")
                            if symbol in self.trader.active_positions:
                                del self.trader.active_positions[symbol]
                            if symbol in self.stock_positions:
                                del self.stock_positions[symbol]
                            return
            
            await asyncio.sleep(0.1) # Tiny delay to allow state to settle
            await self._process_alert(channel, symbol, data, asset_type)
        except Exception as e:
            # Don't spam discovery errors
            if "does not have market symbol" not in str(e):
                print(f"⚠️ Error checking {symbol}: {e}")
        await asyncio.sleep(0.3)

    async def _process_alert(self, channel, symbol, data, asset_type):
        if data is not None:
             # Enable Aggressive Scalping Mode for Crypto/Meme
            is_scalping = asset_type in ["Crypto", "Meme"]
            result = self.analyzer.analyze_trend(data, aggressive_mode=is_scalping)
            
            # Get confidence score (default 0 for backward compatibility)
            confidence = result.get('confidence', 0)
            
            # HIGH CONVICTION FILTER: Only process signals with confidence >= 75
            # This filters to: SMC FVG (90), Sniper (85), Pullback+MACD (75)
            MIN_CONVICTION = 75
            
            # Trigger on BUY, SELL, BULLISH, or BEARISH
            if 'signal' in result and result['signal'] != 'NEUTRAL':
                
                # Skip low-conviction signals entirely (no alert, no trade)
                if asset_type in ["Crypto", "Meme"] and result['signal'] in ['BUY', 'SELL']:
                    if confidence < MIN_CONVICTION:
                        print(f"ℹ️ Analysis for {symbol}: {result['signal']} - Low conviction ({confidence}), skipping")
                        return
                    else:
                        print(f"🔥 HIGH CONVICTION: {symbol} RSI={result.get('rsi', 0):.0f} ({result['reason']})")
                
                # Time-of-Day Filter REMOVED by user request
                # was: if 0 <= hour < 8: skip buy

                # Map colors
                color_map = {
                    'BUY': discord.Color.green(),
                    'SELL': discord.Color.red(),
                    'BULLISH': discord.Color.gold(),
                    'BEARISH': discord.Color.blue()
                }
                color = color_map.get(result['signal'], discord.Color.light_grey())
                
                prefix = "🚀" if result['signal'] in ['BUY', 'SELL'] else "📊"
                title_type = "OPPORTUNITY" if result['signal'] in ['BUY', 'SELL'] else "TREND UPDATE"

                embed = discord.Embed(
                    title=f"{prefix} {asset_type.upper()} {title_type}: {symbol}",
                    description=f"The AI has detected a **{result['signal']}** pattern!",
                    color=color
                )
                embed.add_field(name="Current Price", value=f"${result['price']:.8f}", inline=True)
                embed.add_field(name="RSI (14)", value=result['rsi'], inline=True)
                embed.add_field(name="Analysis", value=result['reason'], inline=False)
                
                # Add context for Trend Alerts
                if result['signal'] in ['BULLISH', 'BEARISH']:
                    embed.set_footer(text=f"Momentum Alert | 1h Timeframe")
                else:
                    embed.set_footer(text=f"High Priority Alert | Technical Extremes")
                
                await channel.send(embed=embed)
                
                # --- SCALPING & AUTO-TRADING LOGIC ---
                if (asset_type in ["Crypto", "Meme"] or asset_type == "Stock") and result['signal'] in ['BUY', 'SELL']:
                    symbol_price = result['price']
                    trade_result = None
                    MAX_POSITIONS = 15
                    
                    # Base trade amount - REDUCED for more positions!
                    base_trade_amount = 5.0  # Was $10, now $5 = 2x more positions
                    trade_amount = base_trade_amount  # Initialize for both BUY and SELL paths
                    scalp_mode = (asset_type == "Meme" or symbol_price < 1.0)

                    if result['signal'] == 'BUY':
                        # 0. Check Restricted List (Session Blacklist)
                        if symbol in self.restricted_assets:
                            print(f"🚫 {symbol} is blacklisted for this session. Skipping.")
                            return
                            
                        # 0a. Check Cooldown (Wash Trade Prevention)
                        if symbol in self.last_exit_times:
                            elapsed = (datetime.datetime.now() - self.last_exit_times[symbol]).total_seconds()
                            if elapsed < 1800: # POSITION TRADER MODE: 30 min cooldown (was 90 sec)
                                print(f"⏳ Cooldown active for {symbol} ({int((1800-elapsed)/60)} min remaining). Skipping buy.")
                                return

                        # 1. Check if we already have a position (local cache)
                        if symbol in self.trader.active_positions:
                            print(f"ℹ️ Buy signal for {symbol} but already holding.")
                            return
                        
                        # Calculate Risk Factor and Conviction Sizing based on RSI
                        rsi = result.get('rsi', 50)
                        risk_factor = 1.0
                        conviction_multiplier = 1.0
                        
                        if rsi < 20:
                            # 🔥 HIGH CONVICTION: Deeply oversold = 2x position
                            risk_factor = 1.5
                            conviction_multiplier = 2.0
                            print(f"🔥 HIGH CONVICTION: {symbol} RSI={rsi:.0f} (Deeply Oversold)")
                        elif rsi < 30:
                            risk_factor = 1.2  # Aggressive Buy (Oversold)
                        elif rsi > 70:
                            risk_factor = 0.5  # Risk Buy (Overbought)
                        
                        # Apply conviction multiplier to trade amount
                        trade_amount = base_trade_amount * conviction_multiplier
                        
                        # 1b. LIVE CHECK: Verify with exchange we don't already hold this (prevents BNB double-buy)
                        if asset_type in ["Crypto", "Meme"]:
                            try:
                                base_asset = symbol.split('/')[0]  # BNB/USDT -> BNB
                                balance = self.crypto.exchange.fetch_balance()
                                held_amount = balance.get('total', {}).get(base_asset, 0)
                                if held_amount > 0:
                                    # Check if worth > $5
                                    ticker = self.crypto.exchange.fetch_ticker(symbol)
                                    if held_amount * ticker['last'] > 5:
                                        # We already hold this, add to tracking and skip buy
                                        self.trader.track_position(symbol, ticker['last'], held_amount)
                                        print(f"ℹ️ Live check: Already holding {held_amount:.4f} {base_asset}. Skipping buy.")
                                        return
                            except Exception as e:
                                print(f"⚠️ Live balance check failed: {e}")

                        # 2. Check position cap (CRYPTO ONLY - stocks have separate cap)
                        crypto_positions = [s for s in self.trader.active_positions.keys() if '/' in s]
                        if len(crypto_positions) >= MAX_POSITIONS:
                            print(f"⚠️ Position cap ({MAX_POSITIONS}) reached. Skipping buy for {symbol}.")
                            return

                        # 3. Automated Safety Audit for small coins
                        if symbol_price < 1.0:
                            await channel.send(f"🛡️ **Scalp Safety Check:** Auditing `{symbol}` before entry...")
                            # Note: For Kraken-listed tokens, we check for high RSI/Volatility instead.
                        
                        if asset_type == "Stock":
                            # Skip if auto-trading disabled or max positions reached
                            if not self.stock_auto_trade:
                                print(f"ℹ️ Stock auto-trading disabled for {symbol}")
                                return
                            if len(self.stock_positions) >= self.stock_max_positions:
                                print(f"⚠️ Max stock positions ({self.stock_max_positions}) reached. Skipping {symbol}.")
                                return
                            
                            # Check buying power before trading
                            account = self.stocks.get_account()
                            if account and account['buying_power'] < self.stock_trade_amount:
                                # Silently skip - not enough buying power
                                return
                            
                            trade_result = self.trader.execute_market_buy_stock(symbol, notional=self.stock_trade_amount)
                            trade_title = "💰 ALPACA: EXECUTED BUY"
                            trade_amount = self.stock_trade_amount
                            
                            if trade_result.get('success'):
                                self.stock_positions[symbol] = trade_result
                            else:
                                # Handle Stock Specific Errors (Wash Trade)
                                err = trade_result.get('error', '').lower()
                                if "wash" in err or "complex order" in err:
                                    print(f"🚫 {symbol} wash trade detected. Blacklisting for session.")
                                    self.restricted_assets.add(symbol)
                                    return
                        else:
                            trade_result = self.trader.execute_market_buy(symbol, amount_usdt=trade_amount, risk_factor=risk_factor)
                            
                            # Handle Restricted Errors
                            if not trade_result.get('success'):
                                err = trade_result.get('error', '')
                                if "valid permissions" in err or "Restricted" in err:
                                    print(f"🚫 {symbol} is restricted. Blacklisting for session.")
                                    self.restricted_assets.add(symbol)
                                    return

                            trade_title = "💰 SCALP: EXECUTED BUY" if scalp_mode else "💰 AUTO-TRADE: EXECUTED BUY"
                    else: # SELL signal
                        if asset_type == "Stock": trade_title = "📉 ALPACA: EXIT OPPORTUNITY"
                        elif scalp_mode: trade_title = "📉 SCALP: EXIT OPPORTUNITY"
                        else: trade_title = "📉 AUTO-TRADE: EXIT OPPORTUNITY"
                        
                        # ONLY execute sell if we actually own the asset
                        has_position = (symbol in self.trader.active_positions or 
                                       (asset_type == "Stock" and symbol in self.stock_positions))
                        
                        if has_position:
                            if asset_type == "Stock":
                                trade_result = self.trader.execute_market_sell_stock(symbol)
                                trade_title = "📉 ALPACA: EXECUTED SELL"
                                if trade_result.get('success') and symbol in self.stock_positions:
                                    del self.stock_positions[symbol]
                            else:
                                trade_result = self.trader.execute_market_sell(symbol)
                                trade_title = "📉 SCALP: EXECUTED SELL" if scalp_mode else "📉 AUTO-TRADE: EXECUTED SELL"
                            
                            # Handle Ghost Positions (Sell failed due to no balance)
                            if trade_result and trade_result.get('error'):
                                err_msg = str(trade_result.get('error', '')).lower()
                                if "insufficient qty" in err_msg or "not found" in err_msg:
                                    print(f"⚠️ Ghost position detected (Sell Failed) for {symbol}. Clearing local state.")
                                    if symbol in self.trader.active_positions:
                                        del self.trader.active_positions[symbol]
                                    if symbol in self.stock_positions:
                                        del self.stock_positions[symbol]

                        else:
                            trade_result = None # No position to sell

                    if trade_result and "error" not in trade_result:
                        # Calculate amount (fallback to cost/price if exchange returns None)
                        amt = trade_result.get('amount')
                        if amt is None:
                            amt = trade_amount / symbol_price

                        # Record position for SL/TP tracking (only for BUYs)
                        if result['signal'] == 'BUY':
                            self.trader.track_position(symbol, symbol_price, amt)
                        
                        # --- RECORD TRADE TO DATABASE ---
                        db = SessionLocal()
                        try:
                            # Use calculated amt
                            new_trade = models.Trade(
                                symbol=symbol,
                                side=result['signal'],
                                asset_type=asset_type.upper(),
                                amount=float(amt),
                                price=float(symbol_price),
                                cost=float(amt * symbol_price),
                                user_id=self.trader.user_id,
                                timestamp=datetime.datetime.utcnow()
                            )
                            db.add(new_trade)
                            db.commit()
                            print(f"📝 Recorded {result['signal']} trade for {symbol} to database.")
                        except Exception as db_err:
                            print(f"❌ Error recording trade to DB: {db_err}")
                        finally:
                            db.close()

                        trade_embed = discord.Embed(
                            title=trade_title,
                            description=f"Automated order for **{symbol}** successful.\n**User:** {self.trader.user_id}",
                            color=discord.Color.dark_gold()
                        )
                        trade_embed.add_field(name="Amount Used", value=f"${trade_amount}", inline=True)
                        trade_embed.add_field(name="Order ID", value=trade_result.get('id', 'N/A'), inline=True)
                        await channel.send(embed=trade_embed)

                    elif trade_result and "error" in trade_result:
                        print(f"❌ Auto-trade failed for {symbol}: {trade_result['error']}")
            else:
                sig = result.get('signal', 'UNKNOWN')
                print(f"ℹ️ Analysis for {symbol}: {sig} - {result.get('reason', 'N/A')}")
            
            return result

    @commands.command()
    async def add_watchlist(self, ctx, symbol: str, category: str = "majors"):
        """Add to watchlist. Usage: !add_watchlist BTC majors OR !add_watchlist DOGE memes"""
        symbol = symbol.upper()
        if '/' not in symbol: symbol = f"{symbol}/USDT"
        
        if category.lower() == "majors":
            if symbol not in self.majors_watchlist:
                self.majors_watchlist.append(symbol)
                await ctx.send(f"✅ Added {symbol} to Majors watchlist.")
        elif category.lower() == "memes":
            if symbol not in self.memes_watchlist:
                self.memes_watchlist.append(symbol)
                await ctx.send(f"✅ Added {symbol} to Memes watchlist.")
        else:
            if symbol not in self.stock_watchlist:
                self.stock_watchlist.append(symbol)
                await ctx.send(f"✅ Added {symbol} to Stock watchlist.")

    @commands.command()
    async def scan(self, ctx):
        """Manually trigger a market scan."""
        if not self.ready:
            await ctx.send("⏳ **System warming up...** Data and traders are loading in the background. Please wait ~30s.")
            return
            
        await ctx.send("⚡ Triggering Full Market Scan summary...")
        
        scan_results = []
        # Majors
        for s in self.majors_watchlist:
            data = self.crypto.fetch_ohlcv(s, timeframe='1h', limit=2)
            if data is not None and not data.empty:
                p = data.iloc[-1]['close']
                scan_results.append(f"🔵 `{s}`: ${p:.2f}")

        # Memes
        for s in self.memes_watchlist:
            data = self.crypto.fetch_ohlcv(s, timeframe='1h', limit=2)
            if data is not None and not data.empty:
                p = data.iloc[-1]['close']
                scan_results.append(f"🟡 `{s}`: ${p:.8f}")

        # DEX
        for item in self.dex_watchlist:
            pair = await self.dex_scout.get_pair_data(item['chain'], item['address'])
            if pair:
                scan_results.append(f"🟣 `{pair['baseToken']['symbol']}`: ${pair['priceUsd']}")

        summary = discord.Embed(title="🔍 Market Status Summary", description="\n".join(scan_results), color=discord.Color.blue())
        await ctx.send(embed=summary)

    @commands.command()
    async def track(self, ctx, address: str, chain: str = "solana"):
        """Track a DEX token by address. Usage: !track HBoNJ... solana"""
        address = address.strip()
        chain = chain.lower()
        
        # Check if already tracked
        if any(item['address'] == address for item in self.dex_watchlist):
            await ctx.send(f"⚠️ `{address}` is already being tracked.")
            return

        await ctx.send(f"🔍 Scouting DEX for `{address}` on {chain.upper()}...")
        pair_data = await self.dex_scout.get_pair_data(chain, address)
        
        if pair_data:
            info = self.dex_scout.extract_token_info(pair_data)
            self.dex_watchlist.append({"chain": chain, "address": address})
            
            embed = discord.Embed(title=f"✅ Now Tracking: {info['symbol']}", color=discord.Color.green())
            embed.add_field(name="Name", value=info['name'], inline=True)
            embed.add_field(name="Price", value=f"${info['price_usd']:.8f}", inline=True)
            embed.add_field(name="Chain", value=chain.upper(), inline=True)
            await ctx.send(embed=embed)
        else:
            await ctx.send(f"❌ Could not find pair for `{address}` on {chain.upper()}. Make sure it's a valid PAIR address on DexScreener.")

    @commands.command()
    async def balance(self, ctx):
        """Check Kraken USDT balance."""
        if not self.ready:
            await ctx.send("⏳ **System warming up...** Trading engines are initializing. Please wait.")
            return
            
        bal = self.trader.get_usdt_balance()
        await ctx.send(f"💰 **Kraken Portfolio Balance:** `{bal}` USDT")

    @commands.command()
    async def help_me(self, ctx):
        """Custom help for degen mode."""
        # Only respond in trading channels
        trading_channels = [self.STOCKS_CHANNEL_ID, self.CRYPTO_CHANNEL_ID, self.MEMECOINS_CHANNEL_ID]
        if ctx.channel.id not in trading_channels:
            return  # Silently ignore in non-trading channels
        
        help_text = (
            "🚀 **DEGEN DEX Commands:**\n"
            "• `!hunt` - Scan for new whale wallets\n"
            "• `!track <addr>` - Track a specific token\n"
            "• `!status` - Show bot health\n"
            "• `!balance` - Check wallet balance\n"
            "• `!sellall` - Emergency liquidation\n"
            "• `!rugcheck <addr>` - Audit a token safety"
        )
        await ctx.send(help_text)

    @commands.command()
    async def hunt(self, ctx):
        """Manually trigger whale wallet discovery."""
        if not self.ready:
            await ctx.send("⏳ **System warming up...** Copy-trader data is loading. Please wait.")
            return
            
        # Prevent concurrent hunts
        if not hasattr(self, '_hunt_lock'):
            self._hunt_lock = False
        
        if self._hunt_lock:
            await ctx.send("⏳ A whale hunt is already in progress. Please wait...")
            return
        
        self._hunt_lock = True
        await ctx.send("🦈 **Starting Whale Hunt...** Scanning trending pairs for profitable traders...")
        
        try:
            # Run in thread to avoid blocking Discord heartbeat
            import asyncio
            new_wallets = await asyncio.to_thread(
                self.copy_trader.scan_market_for_whales_sync, 
                max_pairs=15, 
                max_traders_per_pair=5
            )
            
            total_tracked = len(self.copy_trader.qualified_wallets)
            
            if new_wallets > 0:
                # INSTANT SYNC: Update Helius webhook immediately so new whales are monitored
                print(f"🦈 Hunt found new whales! Registering with Helius...")
                await self.setup_helius_webhook()
                
                embed = discord.Embed(
                    title="🐋 Whale Hunt Complete!",
                    description=f"Discovered **{new_wallets}** new qualified wallets and registered with Helius!",
                    color=discord.Color.green()
                )
                embed.add_field(name="New This Hunt", value=f"{new_wallets} wallets", inline=True)
                embed.add_field(name="Total Tracked", value=f"{total_tracked} wallets", inline=True)
                await ctx.send(embed=embed)
            else:
                await ctx.send(f"📭 No new qualified wallets found. Currently tracking {total_tracked} whales.")
        except Exception as e:
            await ctx.send(f"❌ Hunt failed: {str(e)[:100]}")
        finally:
            self._hunt_lock = False


    @commands.command()
    async def status(self, ctx):
        """Show bot health and performance stats."""
        total_wallets = len(self.copy_trader.qualified_wallets)
        active_positions = sum(len(trader.positions) for trader in self.dex_traders)
        uptime = datetime.datetime.now() - self.bot.start_time if hasattr(self.bot, 'start_time') else "Active"
        
        # Check DB Health
        db_status = "STABLE ✅"
        db_error = ""
        try:
            from database import SessionLocal
            from models import DexPosition
            db = SessionLocal()
            count = db.query(DexPosition).count()
            db.close()
        except Exception as e:
            db_status = "ERROR ❌"
            db_error = str(e)[:40]

        embed = discord.Embed(
            title="📊 DEGEN DEX Bot Status",
            color=discord.Color.gold(),
            timestamp=datetime.datetime.now()
        )
        embed.add_field(name="Alpha Whales", value=f"🐋 {total_wallets}", inline=True)
        embed.add_field(name="Active Trades", value=f"🚀 {active_positions}", inline=True)
        embed.add_field(name="Database", value=f"🏛️ {db_status}", inline=True)
        
        if db_error:
            embed.add_field(name="DB Sync Error", value=f"⚠️ {db_error}", inline=False)
            
        embed.add_field(name="Moon Engine", value=f"🌙 PERSISTENT {'✅' if db_status == 'STABLE ✅' else '❌'}", inline=True)
        
        # Add balance info if available
        if self.dex_traders:
            sol_bal = await self.run_sync(self.dex_traders[0].get_sol_balance)
            embed.add_field(name="Wallet Balance", value=f"💰 {sol_bal:.4f} SOL", inline=False)
            
        embed.set_footer(text=f"Uptime: {uptime}")
        await ctx.send(embed=embed)


    @commands.command()
    async def whales(self, ctx):
        """List currently tracked whale wallets."""
        if not self.ready:
            await ctx.send("⏳ **System warming up...** Loading wallet cache...")
            return
            
        wallets = self.copy_trader.qualified_wallets
        
        if not wallets:
            await ctx.send("📭 No whale wallets tracked yet. Run `!hunt` to discover some!")
            return
        
        embed = discord.Embed(
            title="🐋 Tracked Whale Wallets",
            description=f"Monitoring **{len(wallets)}** qualified wallets",
            color=discord.Color.blue()
        )
        
        for addr, info in list(wallets.items())[:10]:  # Show first 10
            stats = info.get('stats', {})
            embed.add_field(
                name=f"`{addr[:8]}...{addr[-4:]}`",
                value=f"Trades: {stats.get('trade_count', 0)} | Discovered: {info.get('discovered_on', 'Unknown')}",
                inline=False
            )
        
        if len(wallets) > 10:
            embed.set_footer(text=f"...and {len(wallets) - 10} more")
        
        await ctx.send(embed=embed)

    @commands.command()
    async def reset(self, ctx):
        """Reset the whale list (remove all tracked wallets from memory AND database)."""
        if not self.copy_trader:
            await ctx.send("⚠️ Copy Trader not initialized.")
            return
            
        count = len(self.copy_trader.qualified_wallets)
        self.copy_trader.qualified_wallets = {}
        
        # ALSO clear the database table
        try:
            from database import SessionLocal
            from models import WhaleWallet
            db = SessionLocal()
            db.query(WhaleWallet).delete()
            db.commit()
            db.close()
            await ctx.send(f"🧹 **Whale List Reset.** Removed {count} wallets from memory AND database. Run `!hunt` to find fresh ones!")
        except Exception as e:
            await ctx.send(f"🧹 Cleared {count} from memory, but DB clear failed: {str(e)[:50]}")


    @commands.command()
    async def prune(self, ctx, hours: int = 24):
        """Remove whales inactive for > X hours (default 24h). Usage: !prune 24"""
        if not self.copy_trader:
            await ctx.send("⚠️ Copy Trader not initialized.")
            return
            
        before = len(self.copy_trader.qualified_wallets)
        await ctx.send(f"🔍 Checking for whales inactive > {hours} hours...")
        
        pruned = self.copy_trader.prune_lazy_whales(inactive_hours=hours)
        after = len(self.copy_trader.qualified_wallets)
        
        if pruned > 0:
            await ctx.send(f"✂️ **Pruned {pruned} lazy whales!**\n📊 Before: {before} → After: {after} whales tracked.")
        else:
            await ctx.send(f"✅ All {after} whales are active. No lazy whales to prune.")

    @commands.command()
    async def polymarket(self, ctx):
        """Check Polymarket paper trading status."""
        if not POLYMARKET_ENABLED or not self.polymarket_trader:
            await ctx.send("⚠️ Polymarket module is not enabled.")
            return
        
        status = self.polymarket_trader.get_status()
        
        embed = discord.Embed(
            title="🎲 Polymarket Copy-Trader Status",
            color=discord.Color.purple()
        )
        
        # Mode indicator
        mode_emoji = "📝" if status['mode'] == "PAPER" else "💰"
        embed.add_field(name="Mode", value=f"{mode_emoji} {status['mode']}", inline=True)
        embed.add_field(name="Balance", value=f"${status['balance']:.2f}", inline=True)
        embed.add_field(name="Open Positions", value=str(status['open_positions']), inline=True)
        
        embed.add_field(name="Position Value", value=f"${status['total_position_value']:.2f}", inline=True)
        embed.add_field(name="Daily P&L", value=f"${status['daily_pnl']:+.2f}", inline=True)
        embed.add_field(name="Total P&L", value=f"${status['total_pnl']:+.2f}", inline=True)
        
        if status['daily_loss_limit_hit']:
            embed.add_field(name="⚠️ Status", value="Daily loss limit hit - paused", inline=False)
        
        # Show open positions if any
        if self.polymarket_trader.positions:
            pos_list = []
            for token_id, pos in list(self.polymarket_trader.positions.items())[:5]:
                pos_list.append(f"• {pos.outcome}: ${pos.size_usdc:.2f} @ {pos.entry_price:.2f}¢")
            if pos_list:
                embed.add_field(name="📊 Open Positions", value="\n".join(pos_list), inline=False)
        
        await ctx.send(embed=embed)

    @commands.command()
    async def sellprofits(self, ctx):
        """Sell all DEX positions currently in profit. Use for clean slate."""
        if not self.dex_traders:
            await ctx.send("⚠️ No DEX traders configured.")
            return
        
        await ctx.send("🔍 Scanning DEX positions for profitable exits...")
        
        sold_count = 0
        total_pnl = 0.0
        sold_tokens = []
        
        for trader in self.dex_traders:
            user_label = getattr(trader, 'user_id', 'Main')
            
            # Get current prices for all positions
            for token_address, pos in list(trader.positions.items()):
                try:
                    entry_price = pos.get('entry_price_usd', 0)
                    if not entry_price:
                        continue
                    
                    # Fetch current price
                    pair_data = await self.dex_scout.get_pair_data('solana', token_address)
                    if not pair_data:
                        continue
                    
                    info = self.dex_scout.extract_token_info(pair_data)
                    current_price = info.get('price_usd', 0)
                    
                    if not current_price:
                        continue
                    
                    # Calculate P&L
                    pnl_pct = ((current_price - entry_price) / entry_price) * 100
                    
                    # Only sell if in profit
                    if pnl_pct > 0:
                        result = trader.sell_token(token_address)
                        if result.get('success'):
                            sold_count += 1
                            total_pnl += pnl_pct
                            sold_tokens.append(f"✅ {info['symbol']}: +{pnl_pct:.1f}%")
                            
                            # Remove from DB
                            try:
                                db = SessionLocal()
                                db.query(models.DexPosition).filter(
                                    models.DexPosition.token_address == token_address
                                ).delete()
                                db.commit()
                                db.close()
                            except: pass
                        else:
                            sold_tokens.append(f"❌ {info['symbol']}: Failed - {result.get('error', 'Unknown')[:30]}")
                    
                    await asyncio.sleep(0.5)  # Rate limit
                    
                except Exception as e:
                    print(f"Error checking position {token_address[:8]}: {e}")
        
        # Send result
        if sold_count > 0:
            embed = discord.Embed(
                title="🧹 Profitable Positions Sold",
                description=f"Sold **{sold_count}** positions for clean slate.",
                color=discord.Color.green()
            )
            embed.add_field(name="Results", value="\n".join(sold_tokens[:10]), inline=False)
            await ctx.send(embed=embed)
        else:
            await ctx.send("📭 No profitable positions found to sell.")

    @commands.command()
    async def sellall(self, ctx):
        """Sell ALL DEX tokens for all users - emergency liquidation."""
        await ctx.send("🚨 **EMERGENCY LIQUIDATION** - Selling all DEX tokens for all users...")
        
        sold_count = 0
        results = []
        
        for trader in self.dex_traders:
            user_id = getattr(trader, 'user_id', 'Unknown')
            
            # Get all tokens in wallet - NON BLOCKING
            holdings = await self.run_sync(trader.get_all_tokens)
            
            for mint, balance in holdings.items():
                if balance > 0:
                    print(f"🔥 Selling {mint[:16]}... for User {user_id}")
                    result = await self.run_sync(trader.sell_token, mint)
                    
                    if result.get('success'):
                        sold_count += 1
                        results.append(f"✅ User {user_id}: `{mint[:12]}...`")
                        # Clear from positions
                        if mint in trader.positions:
                            del trader.positions[mint]
                    else:
                        results.append(f"❌ User {user_id}: `{mint[:12]}...` - {result.get('error', 'Failed')[:30]}")
        
        if sold_count > 0:
            embed = discord.Embed(
                title="🔥 Emergency Liquidation Complete",
                description=f"Sold **{sold_count}** tokens across all users.",
                color=discord.Color.red()
            )
            embed.add_field(name="Results", value="\n".join(results[:15]), inline=False)
            await ctx.send(embed=embed)
        else:
            await ctx.send("📭 No DEX tokens found to sell.")

    @tasks.loop(seconds=30) # ⚡ Helius Mindful: Polling slowed to 30s to save credits for top 100 real-time webhooks.
    async def swarm_monitor(self):
        """Polls for Swarm Signals (Copy Trading)."""
        # Add jitter to prevent API storms from multiple instances
        import random
        await asyncio.sleep(random.randint(1, 10))
        
        # Set heartbeat FIRST so we know loop is alive
        self.last_swarm_scan = datetime.datetime.now()
            
        try:
            # DIAGNOSTIC: Show cache size every cycle
            cache_size = len(self.copy_trader._recent_whale_activity)
            whale_count = len(self.copy_trader.qualified_wallets)
            if cache_size > 0 or not hasattr(self, '_swarm_diag_tick'):
                print(f"🔍 Swarm Monitor: {cache_size} activities in cache, tracking {whale_count} whales")
            if not hasattr(self, '_swarm_diag_tick'): self._swarm_diag_tick = 0
            self._swarm_diag_tick += 1
            
            # Min Buyers threshold set to 2 for stronger Alpha Consensus (Ultimate Bot)
            # Pass held tokens so swarms aren't pruned while we still hold
            held_tokens = set()
            for trader in self.dex_traders:
                held_tokens.update(trader.positions.keys())
            signals = self.copy_trader.analyze_swarms(min_buyers=3, window_minutes=15, held_tokens=held_tokens)
            
            channel_memes = self.bot.get_channel(self.MEMECOINS_CHANNEL_ID)
            
            if signals:
                print(f"🚀 SWARM ANALYSIS FOUND {len(signals)} SIGNALS: {signals}")

            
            for mint in signals:
                # RACE CONDITION FIX: Check dump blacklist FIRST (before position check)
                # This prevents re-buying a token we just sold due to whale dump
                if hasattr(self, '_dump_blacklist') and mint in self._dump_blacklist:
                    now = datetime.datetime.now().timestamp()
                    if now - self._dump_blacklist[mint] < 3600:  # 60 min cooldown
                        print(f"🚫 Swarm Monitor Skip: {mint[:16]}... (on dump blacklist)")
                        continue
                
                # Anti-Churn: Check re-buy cooldown (2 hours)
                now = datetime.datetime.now().timestamp()
                last_exit = self.dex_exit_cooldowns.get(mint, 0)
                if now - last_exit < 7200: # 2 hour cooldown
                    # self.logger.debug(f"🚫 Skipping re-buy: {mint[:12]}... is on cooldown")
                    continue
                
                # Check if ANY user already has a position
                already_holding = False
                for trader in self.dex_traders:
                    if mint in trader.positions:
                        already_holding = True
                        break
                
                if already_holding:
                    continue
                
                # ALERT MODE: Always send Discord alert for swarms
                if channel_memes:
                    await channel_memes.send(
                        f"🚀🚀🚀 **DEGEN SWARM DETECTED!** 🚀🚀🚀\n"
                        f"Token: `{mint[:16]}...`\n"
                        f"3+ Whales are APING IN! To the moon? 🌕\n"
                        f"Check DEXScreener: https://dexscreener.com/solana/{mint}"
                    )
                
                # Only execute trade if we have a valid DEX wallet
                if self.dex_traders:
                    print(f"🚨 EXECUTING SWARM BUY: {mint}")
                    await self.execute_swarm_trade(mint)

                else:
                    print(f"⚠️ SWARM DETECTED but no DEX wallet loaded - Alert only mode")

            
            # 📉 EXIT HANDLING: Now handled by webhooks (see trigger_instant_exit)
                
            # 3. AUTO-HUNTER: Runs periodically to refresh the whale pool.
            if not hasattr(self, 'swarm_tick'): self.swarm_tick = 0
            self.swarm_tick += 1
            # Run every 2 hours (240 ticks @ 30s) instead of 12 hours
            if self.swarm_tick % 240 == 0:
                print("🦈 Alpha Expansion: Scanning for fresh top-tier whales...")
                # Increase breadth: 25 pairs, 5 traders each
                new_wallets = await self.copy_trader.scan_market_for_whales(max_pairs=25, max_traders_per_pair=5)
                if new_wallets > 0:
                    print(f"✅ Auto-Hunter found {new_wallets} new top-tier alpha wallets!")
                    if channel_memes:
                        await channel_memes.send(f"🦈 **Alpha Expansion** found {new_wallets} new Top PNL whales! Net widened. 🦾")

                
        except Exception as e:
            import traceback
            print(f"❌ Swarm Monitor Error: {e}")
            traceback.print_exc()

    @tasks.loop(seconds=10) # FLASH PROTECTION: Speed increased to 10s for Ultimate Bot
    async def orphan_guard(self):
        """
        🛡️ ORPHAN GUARD: Safety net for stuck positions and failed sells.
        
        1. Process retry queue (failed sells due to slippage)
        2. Time-based exits (30 min profit take, 60 min force exit)
        3. Orphan detection (whale sold but we didn't)
        """
        try:
            if not self.dex_traders:
                return
            
            channel_memes = self.bot.get_channel(self.MEMECOINS_CHANNEL_ID)
            now = datetime.datetime.now().timestamp()
            
            # ========== 1. PROCESS RETRY QUEUE ==========
            retry_items_to_remove = []
            for item in self.sell_retry_queue:
                # Wait at least 30 seconds between retries
                if now - item.get('last_attempt', 0) < 30:
                    continue
                
                token_addr = item['token_address']
                trader = item['trader']
                attempts = item.get('attempts', 0)
                slippage = item.get('slippage_bps', 5000)
                reason = item.get('reason', 'Retry')
                
                # 🛡️ Hardened Check: Verify actual wallet balance before attempting sell
                bal_info = await self.run_sync(trader.get_token_balance, token_addr)
                if bal_info.get('ui_amount', 0) < 0.0001:
                    print(f"🧹 Detecting on-chain exit for {token_addr[:8]}. Clearing retry item.")
                    retry_items_to_remove.append(item)
                    if token_addr in trader.positions:
                        del trader.positions[token_addr]
                    continue

                print(f"🔄 Retry Queue: Selling {token_addr[:16]}... (attempt {attempts + 1}, slippage {slippage // 100}%)")
                
                result = await self.run_sync(trader.sell_token, token_addr, override_slippage=slippage)
                
                if result.get('success'):
                    print(f"✅ Retry SUCCESS: {token_addr[:16]}...")
                    retry_items_to_remove.append(item)
                    if channel_memes:
                        await channel_memes.send(f"🔄 **Retry Exit Succeeded**: Sold stuck position via orphan guard")
                else:
                    item['attempts'] = attempts + 1
                    item['last_attempt'] = now
                    item['slippage_bps'] = slippage
                    
                    if attempts >= 2:
                        print(f"🛑 Retry FAILED after 3 attempts: {token_addr[:16]}... - Manual exit required!")
                        retry_items_to_remove.append(item)
                        if channel_memes:
                            await channel_memes.send(f"🛑 **Manual Exit Required**: Could not sell `{token_addr[:12]}...` after 3 retries")
            
            # Clean up completed/failed items
            for item in retry_items_to_remove:
                if item in self.sell_retry_queue:
                    self.sell_retry_queue.remove(item)
            
            # ========== 2. TIME-BASED EXITS AND ORPHAN DETECTION ==========
            # 2a. PRE-FETCH ALL PRICES (Bulk optimization to avoid 429s)
            all_mints = set()
            for trader in self.dex_traders:
                all_mints.update(trader.positions.keys())
            
            price_map = {}
            if all_mints:
                # Batch in groups of 30 (API limit)
                mint_list = list(all_mints)
                for i in range(0, len(mint_list), 30):
                    batch = mint_list[i:i+30]
                    pairs = await self.dex_scout.get_token_pairs_bulk(batch)
                    if pairs and pairs != "429":
                        for pair in pairs:
                            addr = pair.get('baseToken', {}).get('address')
                            if addr:
                                price_map[addr] = float(pair.get('priceUsd', 0))
                
            for trader in self.dex_traders:
                user_label = getattr(trader, 'user_id', 'Main')
                positions_to_check = list(trader.positions.items())
                
                for token_addr, pos in positions_to_check:
                    # 🛡️ Hardened Check: Verify actual wallet balance (ignore DUST)
                    actual_bal = await self.run_sync(trader.get_token_balance, token_addr)
                    if actual_bal.get('ui_amount', 0) < 0.0001:
                        if actual_bal.get('ui_amount', 0) > 0:
                            print(f"🧹 Detecting DUST position ({actual_bal.get('ui_amount'):.8f}) for {token_addr[:8]}. Pruning.")
                        if token_addr in trader.positions:
                             del trader.positions[token_addr]
                        continue

                    entry_time = pos.get('entry_time', 0)
                    
                    age_mins = (now - entry_time) / 60
                    entry_price = pos.get('entry_price_usd', 0)
                    symbol = pos.get('symbol', token_addr[:8])
                    
                    # 🚀 Bulk Logic: Use pre-fetched price
                    current_price = price_map.get(token_addr, 0)
                    
                    # Fallback for missing prices (one-off check if small set)
                    if current_price == 0 and len(all_mints) < 5:
                        try:
                            pair = await self.dex_scout.get_pair_data("solana", token_addr)
                            if pair:
                                current_price = float(pair.get('priceUsd', 0))
                        except:
                            pass
                    
                    if entry_price and current_price:
                        pnl = ((current_price - entry_price) / entry_price) * 100
                    else:
                        pnl = 0
                    
                    # 🛡️ ULTIMATE BOT: TRAILING STOP LOSS
                    # 1. Update ATH PNL
                    highest_pnl = pos.get('highest_pnl', 0)
                    if pnl > highest_pnl:
                        pos['highest_pnl'] = pnl
                        highest_pnl = pnl
                        #  Moon Engine: Persist highest_pnl to DB
                        try:
                            from database import SessionLocal
                            import models
                            db_session = SessionLocal()
                            # Find the matching position in DB
                            db_pos = db_session.query(models.DexPosition).filter(
                                models.DexPosition.token_address == token_addr,
                                models.DexPosition.wallet_address == trader.wallet_address
                            ).first()
                            if db_pos:
                                db_pos.highest_pnl = pnl
                                db_session.commit()
                            db_session.close()
                        except Exception as e:
                            print(f"⚠️ Failed to persist Moon Engine ATH: {e}")
                    
                    should_exit = False
                    exit_reason = ""
                    
                    # 2. AGGRESSIVE TRAILING STOP (Tiered dropback)
                    # Protect gains by selling if price drops significantly from peak
                    if highest_pnl >= 50.0:
                        # If we hit +50%, protect: sell if drops 15% from peak
                        stop_level = highest_pnl - 15.0
                        if pnl < stop_level:
                            should_exit = True
                            exit_reason = f"📉 Trailing Stop: {pnl:.1f}% (Peak was +{highest_pnl:.1f}%)"
                    elif highest_pnl >= 20.0:
                        # If we hit +20%, protect: sell if drops 8% from peak
                        stop_level = highest_pnl - 8.0
                        if pnl < stop_level:
                            should_exit = True
                            exit_reason = f"📉 Trailing Stop: {pnl:.1f}% (Peak was +{highest_pnl:.1f}%)"
                    
                    # 🛡️ HARD TAKE PROFIT (Secure the bag early)
                    if not should_exit and pnl >= 50:
                        should_exit = True
                        use_priority = True # Moonbag captured, use maximum priority to land
                        exit_reason = f"🌋 50% Moon Exit: +{pnl:.1f}% (Bag Secured!)"

                    # ⏰ Time-based exits (Degen mode: don't marry the coin)
                    if not should_exit:
                        # Profit take earlier (30 mins if green)
                        if age_mins >= 30 and pnl > 0:
                            should_exit = True
                            exit_reason = f"⏰ 30min Profit Take: +{pnl:.1f}%"
                        # Stop loss earlier (30 mins if red)
                        elif age_mins >= 30 and pnl <= -15:
                            should_exit = True
                            exit_reason = f"⏰ 30min Stop: {pnl:.1f}%"
                        # Hard force exit at 60 mins (was 120)
                        elif age_mins >= 60:
                            should_exit = True
                            exit_reason = f"🛡️ 60min Force Exit: {pnl:+.1f}%"
                    
                    # 🚀 CRASH PROTECTION: Use priority for flash crashes
                    if not should_exit and pnl <= -30.0:
                        should_exit = True
                        use_priority = True
                        exit_reason = f"🚨 Crash Detected ({pnl:.1f}%)"
                    
                    # Check if whales are still in (Orphan detection)
                    if not should_exit and age_mins >= 30:
                        if token_addr not in self.copy_trader.active_swarms:
                            should_exit = True
                            exit_reason = f"👻 Orphan Exit: Whales sold ({pnl:+.1f}%)"
                    
                    if should_exit:
                        print(f"🛡️ Orphan Guard: {exit_reason} - {symbol} (User {user_label})")
                        
                        # Calculate USD P/L for alert
                        usd_pnl = 0
                        tokens = pos.get('tokens_received', 0)
                        if tokens > 0 and entry_price > 0 and current_price > 0:
                            usd_pnl = tokens * (current_price - entry_price)
                        elif entry_price > 0 and current_price > 0:
                            # Fallback if tokens missing
                            sol_amt = pos.get('amount_sol', 0.08)
                            pnl_val = (current_price / entry_price - 1)
                            usd_pnl = pnl_val * (sol_amt * 240)
                        
                        hold_time_str = "Unknown"
                        if entry_time:
                            age_sec = datetime.datetime.now().timestamp() - entry_time
                            if age_sec < 60:
                                hold_time_str = f"{int(age_sec)}s"
                            else:
                                hold_time_str = f"{int(age_sec // 60)}m {int(age_sec % 60)}s"

                        # Determine if we should use Priority Jito Tip (2x)
                        priority_val = locals().get('use_priority', False)
                        result = await self.run_sync(trader.sell_token, token_addr, priority=priority_val)
                        
                        if result.get('success'):
                            sig = result.get('signature', 'Unknown')
                            pnl_emoji = "🟢" if pnl >= 0 else "🔴"
                            pnl_sign = "+" if pnl >= 0 else ""
                            usd_sign = "+" if usd_pnl >= 0 else "-"

                            if channel_memes:
                                embed = discord.Embed(
                                    title=f"🛡️ Orphan Guard: {symbol}",
                                    description=f"Automated Safety Exit\n**Reason:** {exit_reason}",
                                    color=discord.Color.blue()
                                )
                                embed.add_field(name="P/L %", value=f"{pnl_emoji} {pnl_sign}{pnl:.1f}%", inline=True)
                                embed.add_field(name="P/L USD", value=f"`{usd_sign}${abs(usd_pnl):.2f}`", inline=True)
                                embed.add_field(name="Hold Time", value=f"`{hold_time_str}`", inline=True)
                                embed.add_field(name="TX", value=f"[`{sig[:32]}...`](https://solscan.io/tx/{sig})", inline=False)
                                await channel_memes.send(embed=embed)
                            
                            # 🛡️ ULTIMATE BOT: WHALE SCORE UPDATE
                            # Reward/Penalize the whales who signaled this trade
                            score_delta = 1.0 if pnl >= 0 else -1.0
                            whales_to_update = self.copy_trader.active_swarms.get(token_addr, set())
                            for addr in whales_to_update:
                                self.copy_trader.update_whale_score(addr, score_delta)
                            
                            # Clear position and set cooldown
                            if token_addr in trader.positions:
                                del trader.positions[token_addr]
                            self.dex_exit_cooldowns[token_addr] = now
                            # Diversity Engine: Clean up active swarm so participants can re-signal later
                            if token_addr in self.copy_trader.active_swarms:
                                del self.copy_trader.active_swarms[token_addr]
                        else:
                            # Add to retry queue
                            print(f"⚠️ Orphan Guard sell failed, adding to retry queue: {token_addr[:16]}...")
                            self.sell_retry_queue.append({
                                'token_address': token_addr,
                                'trader': trader,
                                'reason': exit_reason,
                                'attempts': 0,
                                'last_attempt': now,
                                'slippage_bps': 5000
                            })
                    
                    # Rate limit: small delay between position checks
                    await asyncio.sleep(0.5)
        
        except Exception as e:
            import traceback
            print(f"❌ Orphan Guard Error: {e}")
            traceback.print_exc()


    async def execute_swarm_trade(self, mint):
        """Executes a BUY for a Swarm Signal."""
        # COOLDOWN: Skip recently failed tokens (5 min cooldown)
        if not hasattr(self, '_failed_tokens'):
            self._failed_tokens = {}
        # DUMP BLACKLIST: Skip tokens we recently sold due to whale dump (60 min cooldown)
        if not hasattr(self, '_dump_blacklist'):
            self._dump_blacklist = {}
        
        now = datetime.datetime.now().timestamp()
        
        # ULTIMATE BOT: RE-ENTRY COOLDOWN
        # If we exited this token recently, don't ape back in for 60 minutes
        if mint in self.dex_exit_cooldowns:
            last_exit = self.dex_exit_cooldowns[mint]
            if now - last_exit < 3600:
                print(f"🚫 Skipping {mint[:16]}... (sold recently, 60min re-entry cooldown)")
                return

        # Check dump blacklist FIRST
        if mint in self._dump_blacklist:
            last_dump = self._dump_blacklist[mint]
            if now - last_dump < 3600:  # 60 minute cooldown after dump
                print(f"🚫 Skipping {mint[:16]}... (dumped recently, 60min cooldown)")
                return
            else:
                # Cooldown expired, remove from blacklist
                del self._dump_blacklist[mint]
        
        if mint in self._failed_tokens:
            last_fail = self._failed_tokens[mint]
            if now - last_fail < 300:  # 5 minute cooldown
                print(f"⏳ Skipping {mint[:16]}... (on cooldown after failed trade)")
                return
        
        # ALL TOKENS ALLOWED (Alpha Unlock)
        
        # 1. Get Token Info (Symbol, Liquidity)
        try:
            print(f"🔍 Swarm Trade: Fetching pair data for {mint[:16]}...")
                
            pair = await self.dex_scout.get_pair_data("solana", mint)
            channel_memes = self.bot.get_channel(self.MEMECOINS_CHANNEL_ID)
            
            if not pair:
                # print(f"🚫 Swarm Ignored: No pair data found for {mint[:16]}...")
                # SILENCED DISCORD NOISE to prevent rate limits
                # if channel_memes:
                #     await channel_memes.send(f"🚫 **Swarm Token:** `{mint[:20]}...` - No DEX data found")
                return
            
            print(f"✅ Found DexScreener data for {mint[:16]}!")
            
            symbol = pair.get('baseToken', {}).get('symbol', 'UNKNOWN')
            liquidity = float(pair.get('liquidity', {}).get('usd', 0))
            price = float(pair.get('priceUsd', 0))
            dex_url = f"https://dexscreener.com/solana/{mint}"
            
            # 2. Safety Check (do this first for the embed)
            # 1. ULTIMATE BOT: CONFIDENCE SCORE
            whale_count = len(self.copy_trader.active_swarms.get(mint, set()))
            whales = self.copy_trader.active_swarms.get(mint, set())
            total_confidence = 0
            for addr in whales:
                score = self.copy_trader.qualified_wallets.get(addr, {}).get('score', 10.0)
                total_confidence += score
            
            print(f"Ultimate Bot: Analyzed swarm for {symbol}. Confidence: {total_confidence:.1f} ({whale_count} whales)")
            
            if total_confidence < self.whale_confidence_threshold:
                print(f"🚫 Skipped {symbol}: Confidence {total_confidence:.1f} < {self.whale_confidence_threshold}")
                return

            safety_result = await self.safety.check_solana_token(mint)
            safety_score = safety_result.get('safety_score', 0)
            risks = safety_result.get('risks', [])
            print(f"🛡️ Safety Check: {symbol} scored {safety_score}/100")
            # ULTIMATE BOT: TIERED LIQUIDITY (Alpha Hunter)
            # 10+ Whales = $20k, 5+ Whales = $30k, 3+ Whales = $40k
            
            liq_threshold = 40000 # Default (3 whales)
            if whale_count >= 10: liq_threshold = 20000 # Ultra-early / High Conviction
            elif whale_count >= 5: liq_threshold = 30000 # Aggressive
            elif whale_count >= 3: liq_threshold = 40000 # Standard Alpha Hunter
            
            print(f"📊 Swarm Token: {symbol} | Liq: ${liquidity:,.0f} | Required: ${liq_threshold:,.0f} ({whale_count} whales)")
            
            # --- ALPHA HUNTER: SPECIAL CASE HANDLING ---
            liq_pass = liquidity >= liq_threshold
            safety_pass = safety_score >= 50
            all_pass = liq_pass and safety_pass
            
            # Special bypass for brand new launches (0 liquidity on DexScreener but high whale count)
            is_new_launch = False
            if not liq_pass and liquidity == 0 and whale_count >= 3:
                 print(f"🌊 Brand New Launch Detected: {symbol} (Aping in!)")
                 all_pass = True
                 is_new_launch = True
            
            embed_color = discord.Color.green() if all_pass else discord.Color.red()
            decision = "Ultimate Buy Activated" if all_pass else "Skipped"
            if is_new_launch: decision = "Ultimate Buy Activated (Fresh Launch)"
            
            embed = discord.Embed(
                title=f"Ultimate Bot: {symbol}",
                description=f"**Decision:** {decision} ({whale_count} Whales)",
                color=embed_color
            )
            embed.add_field(name="💰 Liquidity", value=f"${liquidity:,.0f} (Req: ${liq_threshold:,.0f})", inline=True)
            embed.add_field(name="🛡️ Safety", value=f"{safety_score}/100", inline=True)
            embed.add_field(name="💵 Price", value=f"${price:.8f}" if price < 0.01 else f"${price:.4f}", inline=True)
            
            if not all_pass:
                if not liq_pass:
                    print(f"🚫 Skipped {symbol}: Liquidity ${liquidity:,.0f} < ${liq_threshold:,.0f}")
                    embed.add_field(name="❌ Blocked", value=f"Liquidity too low for {whale_count} whales", inline=False)
                elif not safety_pass:
                    embed.add_field(name="❌ Blocked", value=f"Safety score fail ({safety_score})", inline=False)
            elif is_new_launch:
                embed.add_field(name="🌊 Strategy", value="Brand New Launch (High Conviction)", inline=False)

            embed.add_field(name="🔗 DEX", value=f"[View on DexScreener]({dex_url})", inline=False)
            
            channel_memes = self.bot.get_channel(self.MEMECOINS_CHANNEL_ID)
            if channel_memes:
                await channel_memes.send(embed=embed)
            
            if not all_pass:
                return
                
            # 5. ULTIMATE BOT: CONVICTION SIZING (Alpha Hunter v2 - Capital Preservation)
            # 10+ Whales = 0.08 SOL, 5+ Whales = 0.06 SOL, Default (3 Whales) = 0.04 SOL
            amount_sol = 0.04 
            if whale_count >= 10: amount_sol = 0.08
            elif whale_count >= 5: amount_sol = 0.06
            
            print(f"Ultimate Bot: Executing {amount_sol} SOL buy for {symbol} ({whale_count} whales)")


            # NOTE: Emergency safety blocker removed - VPS is now primary server
            
            # 5. Execute for ALL traders (multi-user support)
            channel_memes = self.bot.get_channel(self.MEMECOINS_CHANNEL_ID)
            
            for trader in self.dex_traders:
                user_label = getattr(trader, 'user_id', 'Main')
                
                # Skip if this trader already holds (memory cache)
                if mint in trader.positions:
                    print(f"⏭️ SKIP: User {user_label} already holds {symbol} (cache)")
                    continue
                
                # LIVE CHECK: Query actual wallet to avoid buying after deploy
                try:
                    holdings = trader.get_all_tokens()  # Returns {mint: amount} dict
                    if mint in holdings and holdings[mint] > 0:
                        print(f"⏭️ SKIP: User {user_label} already holds {symbol} (on-chain)")
                        continue
                except Exception as e:
                    print(f"⚠️ Live balance check failed: {e}")
                    # Continue anyway - memory cache check is primary
                
                print(f"🚀 BUYING SWARM (User {user_label}): {symbol} - {amount_sol} SOL")
                # Run sync trading in executor to avoid blocking Discord heartbeat during 30s confirmation wait
                loop = asyncio.get_running_loop()
                result = await loop.run_in_executor(None, trader.buy_token, mint, amount_sol)
                
                if result.get('success'):
                    sig = result.get('signature', 'Unknown')
                    # Log to Discord
                    if channel_memes:
                        embed = discord.Embed(
                            title=f"🐋 SWARM BUY: {symbol}",
                            description=f"Following Smart Money!\n**User:** {user_label}\n**Amount:** {amount_sol} SOL\n**Safety:** {safety_score}/100",
                            color=discord.Color.purple()
                        )
                        embed.add_field(name="TX", value=f"`{sig[:32]}...`", inline=False)
                        await channel_memes.send(embed=embed)
                         
                    # Track Position - MERGE with dex_trader results to keep tokens_received
                    if mint not in trader.positions:
                        trader.positions[mint] = {}
                    
                    trader.positions[mint].update({
                        'entry_price_usd': float(pair.get('priceUsd', 0)),
                        'entry_time': datetime.datetime.now().timestamp(),
                        'amount_sol': amount_sol,
                        'tokens_received': result.get('tokens_received', 0), # NORMALIZED
                        'symbol': symbol,
                        'highest_pnl': 0.0 # Initialize Moon Engine
                    })
                else:
                    # Buy failed - log to Discord and add to cooldown
                    error_msg = result.get('error', 'Unknown error')
                    print(f"❌ Swarm Buy FAILED for {symbol} (User {user_label}): {error_msg}")
                    
                    # Add to cooldown to prevent infinite retries
                    self._failed_tokens[mint] = datetime.datetime.now().timestamp()
                    self.save_failed_tokens()
                    
                    if channel_memes:
                        if "timeout" in error_msg.lower():
                            await channel_memes.send(f"⏳ **Buy Timeout (User {user_label}):** `{symbol}` - TX may have landed. Monitoring wallet for sync... 💎")
                        else:
                            await channel_memes.send(f"❌ **Swarm Buy Failed (User {user_label}):** `{symbol}` - {error_msg[:50]}... (5min cooldown)")


        except Exception as e:
            print(f"❌ Execute Swarm Error: {e}")

    async def trigger_instant_exit(self, mint):
        """
        Execute instant sell when whale sells detected.
        Called by webhook_listener when whales dump a token we hold.
        """
        try:
            channel_memes = self.bot.get_channel(self.MEMECOINS_CHANNEL_ID)
            
            # Find symbol from DexScreener
            symbol = mint[:8]  # Fallback
            try:
                import requests
                resp = requests.get(f"https://api.dexscreener.com/latest/dex/tokens/{mint}", timeout=5)
                if resp.status_code == 200:
                    pairs = resp.json().get('pairs', [])
                    if pairs:
                        symbol = pairs[0].get('baseToken', {}).get('symbol', symbol)
            except:
                pass
            
            print(f"🚨 INSTANT EXIT: Whales selling {symbol} ({mint[:16]}...)!")
            
            if channel_memes:
                await channel_memes.send(f"🚨 **WHALE SELL DETECTED!** 📉\n`{symbol}` - Checking positions...")
            
            # RACE CONDITION FIX: Add to blacklist IMMEDIATELY before any sell attempts
            # This prevents swarm_monitor from triggering re-buys during the sell process
            if not hasattr(self, '_dump_blacklist'):
                self._dump_blacklist = {}
            self._dump_blacklist[mint] = datetime.datetime.now().timestamp()
            
            # Also remove from active swarms to prevent further signals
            if mint in self.copy_trader.active_swarms:
                del self.copy_trader.active_swarms[mint]
                self.copy_trader._delete_swarm_from_db(mint)
            
            print(f"🚫 Blacklisted {mint[:16]}... (60min cooldown)")
            
            # Execute sell for ALL traders who hold this token
            for trader in self.dex_traders:
                user_label = getattr(trader, 'user_id', 'Main')
                
                # SAFETY CHECK 1: Must be in our tracked positions
                if mint not in trader.positions:
                    print(f"⚠️ Exit skipped (User {user_label}): {symbol} not in tracked positions")
                    continue
                
                # SAFETY CHECK 2: Verify position has entry_time (was bought by bot)
                position = trader.positions.get(mint, {})
                if not position.get('entry_time'):
                    print(f"⚠️ Exit skipped (User {user_label}): {symbol} has no entry_time (not bought by bot)")
                    del trader.positions[mint]  # Clean up ghost position
                    continue
                
                # SAFETY CHECK 3: Verify we actually have tokens to sell - NON BLOCKING
                balance_info = await self.run_sync(trader.get_token_balance, mint)
                actual_balance = balance_info.get('ui_amount', 0) if isinstance(balance_info, dict) else 0
                if actual_balance <= 0:
                    print(f"⚠️ Exit skipped (User {user_label}): {symbol} balance is 0 (already sold or dust)")
                    del trader.positions[mint]  # Clean up ghost position
                    continue
                    
                print(f"📉 SELLING (User {user_label}): {symbol} (Balance: {actual_balance:.6f})")
                

                
                # Run sync trading in executor - USE PRIORITY FOR INSTANT EXITS
                result = await self.run_sync(trader.sell_token, mint, 100, None, True)
                
                if result.get('success'):
                    sig = result.get('signature', 'Unknown')
                    
                    # USD P/L Calculation
                    entry_price = position.get('entry_price_usd', 0)
                    exit_price = 0
                    try:
                        # Use DexScout (Async) instead of requests
                        pair_data = await self.dex_scout.get_pair_data("solana", mint)
                        if pair_data:
                            exit_price = float(pair_data.get('priceUsd', 0))
                    except:
                        pass
                    
                    pnl_pct = 0
                    usd_pnl = 0
                    if entry_price > 0 and exit_price > 0:
                        pnl_pct = (exit_price / entry_price - 1) * 100
                        tokens = position.get('tokens_received', 0)
                        if tokens > 0:
                            # NORMALIZED CALCULATION: tokens * (exit - entry)
                            usd_pnl = tokens * (exit_price - entry_price)
                        else:
                            # Fallback (Less accurate)
                            entry_sol = position.get('amount_sol', 0.08)
                            sol_price_est = 240 # rough SOL price
                            usd_pnl = (pnl_pct / 100) * (entry_sol * sol_price_est)

                    pnl_emoji = "🟢" if pnl_pct >= 0 else "🔴"
                    pnl_sign = "+" if pnl_pct >= 0 else ""
                    usd_sign = "+" if usd_pnl >= 0 else "-"
                    
                    # Format hold time
                    hold_time_str = "Unknown"
                    if position.get('entry_time'):
                        age_sec = datetime.datetime.now().timestamp() - position['entry_time']
                        if age_sec < 60:
                            hold_time_str = f"{int(age_sec)}s"
                        else:
                            hold_time_str = f"{int(age_sec // 60)}m {int(age_sec % 60)}s"

                    # Remove from positions
                    if mint in trader.positions:
                        del trader.positions[mint]
                    
                    if channel_memes:
                        embed = discord.Embed(
                            title=f"📉 WHALE EXIT: {symbol}",
                            description=f"Following Smart Money EXIT!\n**User:** {user_label}",
                            color=discord.Color.orange()
                        )
                        embed.add_field(name="P/L %", value=f"{pnl_emoji} {pnl_sign}{pnl_pct:.1f}%", inline=True)
                        embed.add_field(name="P/L USD", value=f"`{usd_sign}${abs(usd_pnl):.2f}`", inline=True)
                        embed.add_field(name="Hold Time", value=f"`{hold_time_str}`", inline=True)
                        embed.add_field(name="TX", value=f"[`{sig[:32]}...`](https://solscan.io/tx/{sig})", inline=False)
                        await channel_memes.send(embed=embed)
                else:
                    error_msg = result.get('error', 'Unknown error')
                    print(f"❌ Instant Exit FAILED for {symbol} (User {user_label}): {error_msg}")
                    if channel_memes:
                        await channel_memes.send(f"❌ **Exit Failed (User {user_label}):** `{symbol}` - {error_msg[:50]}...")
                        
        except Exception as e:
            print(f"❌ Instant Exit Error: {e}")



    @commands.command()
    async def status(self, ctx):
        """Show system health and monitoring status."""
        
        # 1. Swarm Monitor Status
        if hasattr(self, 'last_swarm_scan'):
            delta = datetime.datetime.now() - self.last_swarm_scan
            scan_msg = f"Last scan: **{int(delta.total_seconds())}s ago**"
            heartbeat = "❤️ **Active**"
        else:
            scan_msg = "Last scan: **Never**"
            heartbeat = "⚠️ **Waiting...**"
            
        # 2. Tracking Count
        wallets = len(self.copy_trader.qualified_wallets) if self.copy_trader else 0
        
        # 3. Settings
        mode = "🐋 **Copy-Trading Only**" if not self.dex_auto_trade else "🔫 **Sniper Mode**"
        
        embed = discord.Embed(title="🏥 System Status", color=discord.Color.teal())
        embed.add_field(name="Monitor Heartbeat", value=heartbeat, inline=True)
        embed.add_field(name="Whale Scan", value=scan_msg, inline=True)
        embed.add_field(name="Tracked Wallets", value=f"**{wallets}** whales", inline=True)
        embed.add_field(name="Trading Mode", value=mode, inline=False)
        
        # 4. Resources
        try:
             # Basic mem check if possible, or just skip
             pass
        except: pass
        
        await ctx.send(embed=embed)

    @swarm_monitor.before_loop
    async def before_swarm_monitor(self):
        await self.bot.wait_until_ready()

    @tasks.loop(minutes=10)
    async def polymarket_monitor(self):
        """Monitor Polymarket for whale swarm signals. DISABLED for Ultimate Bot."""
        return # FULL DISABLE - Ultimate Bot focus is memes only.
        
        try:
            # 1. Detect whale swarms
            swarm_signals = await self.polymarket_collector.detect_whale_swarm(
                min_whales=3,
                time_window_minutes=60
            )
            
            if not swarm_signals:
                return
            
            print(f"🐋 Polymarket: Found {len(swarm_signals)} swarm signals")
            
            for signal in swarm_signals:

                try:
                    evaluation = await self.polymarket_trader.evaluate_swarm_signal(signal)
                    
                    if not evaluation:
                        continue
                        
                    if evaluation.get("action") == "BUY":
                        # 3. Execute
                        result = await self.polymarket_trader.execute_buy(
                            token_id=signal.get("token_id"),
                            amount_usdc=evaluation.get("bet_size", 0),
                            whale_count=signal.get("whale_count", 0)
                        )
                        
                        if result and result.get("success"):
                            mode = "PAPER" if self.polymarket_trader.config.paper_mode else "LIVE"
                            whale_count = signal.get('whale_count', 0) or 0
                            bet_size = evaluation.get('bet_size', 0) or 0
                            print(f"🎲 [{mode}] Polymarket BUY: {whale_count} whales @ ${bet_size}")
                    else:
                        reason = evaluation.get('reason', 'Unknown')
                        # Check for None just in case
                        if reason is None: reason = "Unknown"
                        print(f"🔍 Polymarket Skip: {reason}")
                except Exception as inner_e:
                    print(f"⚠️ Error processing Polymarket signal: {inner_e}")
                    continue
            
            # 4. Check for exits on existing positions
            # Get current prices for all positions
            current_prices = {}
            for token_id in self.polymarket_trader.positions.keys():
                price = await self.polymarket_collector.get_market_price(token_id)
                if price:
                    current_prices[token_id] = price
            
            exits = await self.polymarket_trader.check_position_exits(current_prices)
            for exit_data in exits:
                result = await self.polymarket_trader.execute_sell(exit_data.get("token_id"))
                if result and result.get("success"):
                    pnl_val = float(result.get('pnl', 0) or 0)
                    reason = exit_data.get('reason', 'Exit')
                    print(f"🎲 Polymarket EXIT: {reason} (PNL: ${pnl_val:.2f})")
                    
        except Exception as e:
            print(f"❌ Polymarket Monitor Error: {e}")
    
    @polymarket_monitor.before_loop
    async def before_polymarket_monitor(self):
        await self.bot.wait_until_ready()

    async def cog_load(self):
        """Called when the cog is loaded - start the monitoring loops."""
        print("Ultimate Bot: Cog loaded. Full Meme Focus active.")
        # DISABLE POLYMARKET (User request: Full memes only)
        global POLYMARKET_ENABLED
        POLYMARKET_ENABLED = False
        
        # INSTANT Handshake: Schedule the heavy loading in a separate background task
        self._init_task = asyncio.create_task(self._async_background_init())
        
    async def _async_background_init(self):
        """Full asynchronous initialization that won't block Cog registration."""
        try:
            print("⏳ AlertSystem: Background loading started...")
            # 1. Heavy lifting in a thread
            await asyncio.to_thread(self._heavy_initialization_sync)
            
            # 2. Start the monitoring loops
            if not self.monitor_market.is_running():
                self.monitor_market.start()
            if not self.discovery_loop.is_running():
                self.discovery_loop.start()
            if not self.kraken_discovery_loop.is_running():
                self.kraken_discovery_loop.start()
            if not self.swarm_monitor.is_running():
                self.swarm_monitor.start()
                print("🐋 Swarm Monitor started!")
            if POLYMARKET_ENABLED and not self.polymarket_monitor.is_running():
                self.polymarket_monitor.start()
                print(f"🎲 Polymarket Monitor started")
                
            # 3. Webhook and Sync
            await self.setup_helius_webhook()
            await self._startup_sync()
            
            # 🛡️ ORPHAN GUARD: Start the profit-taking/trailing stop loop
            if not self.orphan_guard.is_running():
                self.orphan_guard.start()
                print("🛡️ Orphan Guard started (30s profit-taking loop)!")
            
            self.ready = True
            print(f"✅ AlertSystem: Background initialization COMPLETE. System is READY.")
        except Exception as e:
            import traceback
            print(f"❌ Error during background initialization: {e}")
            traceback.print_exc()

    def _heavy_initialization_sync(self):
        """Perform all blocking DB and API key loading here."""
        # 0. Initialize Primary Singletons
        from collectors.crypto_collector import CryptoCollector
        # from collectors.stock_collector import StockCollector  # Disabled: alpaca not used
        
        # Safe to initialize here in the thread
        if not self.crypto:
            self.crypto = CryptoCollector()
        # StockCollector disabled - alpaca_trade_api not installed
        # if not self.stocks:
        #     self.stocks = StockCollector()
        if not self.trader:
            self.trader = TradingExecutive(user_id=1)
            print("✅ Default TradingExecutive initialized in background.")

        # 1. Load SmartCopyTrader Data
        if self.copy_trader:
            self.copy_trader.load_data()
            
        # 2. Load Solana Keys
        if DEX_TRADING_ENABLED:
            try:
                db = SessionLocal()
                keys = db.query(models.ApiKey).filter(models.ApiKey.exchange == 'solana').all()
                added_wallets = set()
                for k in keys:
                    try:
                        priv = decrypt_key(k.api_key)
                        dt = DexTrader(private_key=priv)
                        if dt.wallet_address and dt.wallet_address not in added_wallets:
                            dt.user_id = k.user_id 
                            self.dex_traders.append(dt)
                            added_wallets.add(dt.wallet_address)
                            print(f"🔓 Loaded Wallet via DB: {dt.wallet_address[:8]}... (User {k.user_id})")
                    except Exception as e:
                        print(f"⚠️ Failed to load key for User {k.user_id}: {e}")
                
                env_key = os.getenv('SOLANA_PRIVATE_KEY')
                if env_key:
                    try:
                        dt = DexTrader(private_key=env_key)
                        if dt.wallet_address and dt.wallet_address not in added_wallets:
                            dt.user_id = "ENV"
                            self.dex_traders.append(dt)
                            print(f"🔓 Loaded Wallet via ENV: {dt.wallet_address[:8]}...")
                    except: pass
                db.close()
                self.dex_trader = self.dex_traders[0] if self.dex_traders else None
            except Exception as e:
                print(f"⚠️ Failed to load Solana keys: {e}")

        # 3. Load Kraken Keys
        try:
            db = SessionLocal()
            kraken_keys = db.query(models.ApiKey).filter(models.ApiKey.exchange == 'kraken').all()
            for k in kraken_keys:
                try:
                    ak, ask = decrypt_key(k.api_key), decrypt_key(k.api_secret)
                    if ak and ask:
                        te = TradingExecutive(api_key=ak, secret_key=ask, user_id=k.user_id)
                        if te.exchange and te.exchange.apiKey:
                            self.kraken_traders.append(te)
                            print(f"💰 Loaded Kraken keys for User {k.user_id}")
                except Exception as e:
                    print(f"⚠️ Failed to load Kraken keys for User {k.user_id}: {e}")
            
            env_ak, env_ask = os.getenv('KRAKEN_API_KEY'), os.getenv('KRAKEN_SECRET_KEY')
            if env_ak and env_ask and not any(t.user_id == 1 for t in self.kraken_traders):
                te = TradingExecutive(api_key=env_ak, secret_key=env_ask, user_id=1)
                if te.exchange and te.exchange.apiKey:
                    self.kraken_traders.append(te)
            db.close()
            self.trader = self.kraken_traders[0] if self.kraken_traders else TradingExecutive(user_id=1)
        except Exception as e:
            print(f"⚠️ Failed to load Kraken traders: {e}")

        # 4. Load Alpaca Keys
        try:
            db = SessionLocal()
            alpaca_keys = db.query(models.ApiKey).filter(models.ApiKey.exchange == 'alpaca').all()
            for k in alpaca_keys:
                try:
                    ak = decrypt_key(k.api_key) if k.api_key else k.api_key
                    ask = decrypt_key(k.api_secret) if k.api_secret else k.api_secret
                    if ak and ask:
                        te = TradingExecutive(alpaca_key=ak, alpaca_secret=ask, user_id=k.user_id)
                        if te.stock_api:
                            self.alpaca_traders.append(te)
                            print(f"📈 Loaded Alpaca keys for User {k.user_id}")
                except Exception as e:
                    print(f"⚠️ Failed to load Alpaca keys for User {k.user_id}: {e}")
            db.close()
        except Exception as e:
            print(f"⚠️ Failed to load Alpaca traders: {e}")

    async def setup_helius_webhook(self):
        """Helper to register/update Helius webhook with all qualified wallets."""
        try:
            webhook_url = os.getenv('HELIUS_WEBHOOK_URL')
            if not webhook_url:
                print("⚠️ HELIUS_WEBHOOK_URL not found. Real-time monitoring disabled.")
                return False
                
            # Get ALL qualified wallet addresses
            wallets = list(self.copy_trader.qualified_wallets.keys())
            if not wallets:
                print("📭 No whale wallets to monitor (yet).")
                return False
                
            print(f"📡 Registering Helius Webhook at {webhook_url} (Monitoring {len(wallets)} addresses)...")
            
            # Use WalletCollector utility to upsert
            from collectors.wallet_collector import WalletCollector
            collector = WalletCollector()
            result = collector.upsert_helius_webhook(webhook_url, wallets)
            
            if result and result.get('webhookID'):
                print(f"✅ Helius Webhook Setup SUCCESS: {result['webhookID']}")
                return True
            else:
                print(f"❌ Helius Webhook Setup FAILED: {result}")
                return False
        except Exception as e:
            print(f"❌ Error setting up Helius Webhook: {e}")
            return False

async def setup(bot):
    await bot.add_cog(AlertSystem(bot))
