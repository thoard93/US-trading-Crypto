import discord
from discord.ext import tasks, commands
import asyncio
import datetime
from collectors.crypto_collector import CryptoCollector
from collectors.stock_collector import StockCollector
from analysis.technical_engine import TechnicalAnalysis
from trading_executive import TradingExecutive
from collectors.dex_scout import DexScout
from analysis.safety_checker import SafetyChecker
from database import SessionLocal
import models

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
        self.crypto = CryptoCollector()
        self.stocks = StockCollector()
        self.analyzer = TechnicalAnalysis()
        self.trader = TradingExecutive(user_id=1)
        self.dex_scout = DexScout()
        self.safety = SafetyChecker()
        
        # Initialize DEX trader for Solana memecoins
            # Load keys for ALL users
            self.dex_traders = []
            try:
                db = SessionLocal()
                # Fetch ALL Solana keys
                keys = db.query(models.ApiKey).filter(models.ApiKey.exchange == 'solana').all()
                
                # Set to track uniqueness
                added_wallets = set()
                
                for k in keys:
                    try:
                        priv = decrypt_key(k.api_key)
                        dt = DexTrader(private_key=priv)
                        if dt.wallet_address and dt.wallet_address not in added_wallets:
                            # Attach user_id for logging
                            dt.user_id = k.user_id 
                            self.dex_traders.append(dt)
                            added_wallets.add(dt.wallet_address)
                            print(f"🔓 Loaded Wallet via DB: {dt.wallet_address[:8]}... (User {k.user_id})")
                    except Exception as e:
                        print(f"⚠️ Failed to load key for User {k.user_id}: {e}")
                
                # Fallback: ENV key
                import os
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
            except Exception as e:
                print(f"⚠️ Failed to load Solana keys: {e}")

            # Legacy pointer (use first trader as primary reference)
            self.dex_trader = self.dex_traders[0] if self.dex_traders else None
            
            if self.dex_traders:
                print(f"🦊 DEX Auto-Trading ENABLED for {len(self.dex_traders)} wallets.")
        else:
            self.dex_traders = []
            self.dex_trader = None
        
        # DEX Auto-trading configuration
        self.dex_auto_trade = True  # Toggle for DEX auto-trading
        self.dex_min_safety_score = 50  # Lowered from 70 to 50 for MAXIMUM ACTION
        self.dex_min_liquidity = 2000  # Lowered from $5k to $2k for fresh gems
        self.dex_max_positions = 5  # Increased from 3 to 5
        
        # STOCK Auto-trading configuration
        self.stock_auto_trade = True  # Toggle for stock auto-trading
        self.stock_trade_amount = 5.0  # $5 per trade (fractional shares)
        self.stock_max_positions = 5  # Max concurrent stock positions
        self.stock_positions = {}  # Track stock positions locally
        
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

        self.monitor_market.start()
        self.dex_monitor.start() # Start new 30s loop
        self.discovery_loop.start()
        self.kraken_discovery_loop.start()
        
        # Async startup tasks
        asyncio.create_task(self._startup_sync())

    async def _startup_sync(self):
        """Wait for bot to be ready and sync existing positions."""
        if not self.bot.is_ready():
            await self.bot.wait_until_ready()
        print("📥 Bot ready. Synchronizing live positions from Kraken...")
        self.trader.sync_positions()
        
        # Log DEX trading status
        if self.dex_trader and self.dex_trader.wallet_address:
            sol_balance = self.dex_trader.get_sol_balance()
            print(f"💰 DEX Wallet SOL Balance: {sol_balance:.4f} SOL")
        
        # Sync Stock positions from Alpaca (CRITICAL: prevents wash trade errors)
        if self.stocks and self.stocks.api:
            try:
                positions = self.stocks.api.list_positions()
                for pos in positions:
                    symbol = pos.symbol
                    self.stock_positions[symbol] = {
                        'qty': float(pos.qty),
                        'avg_entry_price': float(pos.avg_entry_price),
                        'market_value': float(pos.market_value)
                    }
                print(f"📈 Synced {len(positions)} Alpaca positions: {list(self.stock_positions.keys())}")
                
                account = self.stocks.get_account()
                if account:
                    print(f"💵 Alpaca - Cash: ${account['cash']:.2f}, Buying Power: ${account['buying_power']:.2f}")
            except Exception as e:
                print(f"⚠️ Failed to sync Alpaca positions: {e}")



    def cog_unload(self):
        self.monitor_market.cancel()
        self.discovery_loop.cancel()
        self.kraken_discovery_loop.cancel()

    @tasks.loop(minutes=2)  # DAY TRADER MODE: Was 5 min, now 2 min
    async def monitor_market(self):
        if not self.bot.is_ready():
            await self.bot.wait_until_ready()

        channel_crypto = self.bot.get_channel(self.CRYPTO_CHANNEL_ID)
        channel_memes = self.bot.get_channel(self.MEMECOINS_CHANNEL_ID)
        channel_stocks = self.bot.get_channel(self.STOCKS_CHANNEL_ID)

        # 0. Monitor Active Positions (Critical for SL/TP compliance)
        all_owned = list(self.trader.active_positions.keys())
        if all_owned:
            print(f"🛡️ Monitoring {len(all_owned)} active positions for exits...")
            for symbol in all_owned:
                # Detect asset type based on symbol format
                a_type = "Stock" if "/" not in symbol else "Crypto"
                if a_type == "Crypto" and channel_crypto:
                    await self._check_and_alert(symbol, channel_crypto, a_type)
                elif a_type == "Stock" and channel_stocks:
                    await self._check_and_alert(symbol, channel_stocks, a_type)

        # 1. Monitor Majors
        print(f"Checking major crypto: {self.majors_watchlist}")
        if channel_crypto:
            for symbol in self.majors_watchlist:
                if symbol not in self.restricted_assets:
                    await self._check_and_alert(symbol, channel_crypto, "Crypto")

        # 2. Monitor Memes (on Kraken)
        print(f"Checking memecoins: {self.memes_watchlist}")
        if channel_memes:
            for symbol in self.memes_watchlist:
                if symbol not in self.restricted_assets:
                    await self._check_and_alert(symbol, channel_memes, "Meme")



        # 3. Monitor Stocks
        print(f"Checking stock markets: {self.stock_watchlist}")
        if channel_stocks:
            for symbol in self.stock_watchlist:
                # Skip restricted assets
                if symbol not in self.restricted_assets:
                    await self._check_and_alert(symbol, channel_stocks, "Stock")
                await asyncio.sleep(1)

    @tasks.loop(seconds=15)  # DAY TRADER MODE: Was 30s, now 15s (sniper speed)
    async def dex_monitor(self):
        """Dedicated high-speed loop for DEX memecoins (30s)."""
        if not self.bot.is_ready():
            return

        channel_memes = self.bot.get_channel(self.MEMECOINS_CHANNEL_ID)
        
        # Monitor DEX Scout (New Gems) + Auto-Trade
        # print(f"⚡ DEX Monitor: Scouting {len(self.dex_watchlist)} tokens...")
        if channel_memes:
            # Combined list of manual watchlist and trending gems
            all_dex = self.dex_watchlist + self.trending_dex_gems
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
                            embed.add_field(name="Price USD", value=f"${info['price_usd']:.8f}", inline=True)
                            embed.add_field(name="5m Change", value=f"+{info['price_change_5m']}%", inline=True)
                            embed.add_field(name="Liquidity", value=f"${liquidity:,.0f}", inline=True)
                            embed.add_field(name="Safety Score", value=f"**{safety_score}/100**", inline=True)
                            
                            trade_happened = False
                            
                            # AUTO-TRADE logic (Multi-User)
                            if (self.dex_auto_trade and 
                                self.dex_traders and 
                                info['chain'] == 'solana'):
                                
                                if safety_score >= self.dex_min_safety_score and liquidity >= self.dex_min_liquidity:
                                    
                                    # Execute for EACH trader
                                    for trader in self.dex_traders:
                                        dex_positions = len(trader.positions)
                                        
                                        if dex_positions < self.dex_max_positions:
                                            if token_address not in trader.positions:
                                                trade_result = trader.buy_token(token_address)
                                                
                                                user_label = getattr(trader, 'user_id', 'Main')
                                                
                                                if trade_result.get('success'):
                                                    # New: Record entry price for PnL tracking
                                                    trader.positions[token_address]['entry_price_usd'] = info['price_usd']
                                                    trade_happened = True
                                                    embed.add_field(
                                                        name=f"🤖 BOUGHT (User {user_label})", 
                                                        value=f"TX: `{trade_result['signature'][:15]}...`", 
                                                        inline=False
                                                    )
                                                    embed.color = discord.Color.green()
                                                else:
                                                    embed.add_field(name=f"⚠️ Failed (User {user_label})", value=trade_result.get('error', 'Unknown'), inline=False)
                                        else:
                                            # Already holding
                                            pass
                            
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
                                    
                                    if entry_price:
                                        pnl = ((info['price_usd'] - entry_price) / entry_price) * 100
                                        if pnl >= 20.0: # TP: +20% (Tighter to secure wins)
                                            should_sell = True
                                            reason = f"🎯 Take Profit (+{pnl:.1f}%)"
                                        elif pnl <= -10.0: # SL: -10% (Tighter to prevent bags)
                                            should_sell = True
                                            reason = f"🛑 Stop Loss ({pnl:.1f}%)"
                                    
                                    # Fallback dump check
                                    if not should_sell and info['price_change_5m'] <= -15.0:
                                        should_sell = True
                                        reason = f"🚨 Crash Detected (-15% in 5m)"
                                        
                                    if should_sell:
                                        trader.sell_token(token_address)
                                        await channel_memes.send(f"{reason}: USER {user_label} Sold {info['symbol']}")

                except Exception as ex:
                    print(f"⚠️ Error checking DEX token {item.get('address')}: {ex}")
                
                await asyncio.sleep(0.5)

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

    @tasks.loop(minutes=2)  # SNIPER MODE: Was 10 min, now 2 min
    async def discovery_loop(self):
        """Find new trending DEX gems automatically - SNIPER MODE."""
        if not self.bot.is_ready(): return
        
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
                        
                        if channel_memes:
                            embed = discord.Embed(
                                title=f"🎯 SNIPER TARGET: {pair.get('baseToken', {}).get('symbol')}",
                                description=f"**+{change_5m:.1f}%** in 5min | Safety: {safety_score}/100",
                                color=discord.Color.gold()
                            )
                            embed.add_field(name="Price", value=f"${float(pair.get('priceUsd', 0)):.8f}", inline=True)
                            embed.add_field(name="Liquidity", value=f"${liquidity:,.0f}", inline=True)
                            
                            # IMMEDIATE SNIPE when discovery finds a good gem
                            if (self.dex_auto_trade and 
                                self.dex_trader and 
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
        if not self.bot.is_ready(): return
        
        print("🔍 Running Kraken Market Discovery...")
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
            core_majors = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'XRP/USDT']
            core_memes = ['DOGE/USDT', 'SHIB/USDT', 'ADA/USDT']
            
            self.majors_watchlist = sorted(list(set(core_majors + new_majors[:8])))
            self.memes_watchlist = sorted(list(set(core_memes + new_memes[:12])))
            
            print(f"✅ Kraken Watchlist Updated: Majors({len(self.majors_watchlist)}), Memes({len(self.memes_watchlist)})")
            
        except Exception as e:
            print(f"❌ Kraken Discovery error: {e}")

    async def _process_alert(self, channel, symbol, data, asset_type):
        if data is not None:
            result = self.analyzer.analyze_trend(data)
            # Trigger on BUY, SELL, BULLISH, or BEARISH
            if 'signal' in result and result['signal'] != 'NEUTRAL':
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
                    MAX_POSITIONS = 10
                    
                    # Kraken requires ~$10 minimum for most pairs
                    trade_amount = 10.0 
                    scalp_mode = (asset_type == "Meme" or symbol_price < 1.0)

                    if result['signal'] == 'BUY':
                        # 0. Check Restricted List (Session Blacklist)
                        if symbol in self.restricted_assets:
                            print(f"🚫 {symbol} is blacklisted for this session. Skipping.")
                            return
                            
                        # 0a. Check Cooldown (Wash Trade Prevention)
                        if symbol in self.last_exit_times:
                            elapsed = (datetime.datetime.now() - self.last_exit_times[symbol]).total_seconds()
                            if elapsed < 90: # DAY TRADER MODE: 90 second cooldown (was 5 min)
                                print(f"⏳ Cooldown active for {symbol} ({int(90-elapsed)}s remaining). Skipping buy.")
                                return

                        # 1. Check if we already have a position (local cache)
                        if symbol in self.trader.active_positions:
                            print(f"ℹ️ Buy signal for {symbol} but already holding.")
                            return
                        
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

                        # 2. Check position cap
                        if len(self.trader.active_positions) >= MAX_POSITIONS:
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
                            trade_result = self.trader.execute_market_buy(symbol, amount_usdt=trade_amount)
                            
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
                        # Record position for SL/TP tracking (only for BUYs)
                        if result['signal'] == 'BUY':
                            self.trader.track_position(symbol, symbol_price, trade_result.get('amount', 0))
                        
                        # --- RECORD TRADE TO DATABASE ---
                        db = SessionLocal()
                        try:
                            # Use amount from trade_result if possible, else fallback to trade_amount / price
                            amt = trade_result.get('amount') or (trade_amount / symbol_price)
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
                            description=f"Automated order for **{symbol}** successful.",
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
        bal = self.trader.get_usdt_balance()
        await ctx.send(f"💰 **Kraken Portfolio Balance:** `{bal}` USDT")

async def setup(bot):
    await bot.add_cog(AlertSystem(bot))
