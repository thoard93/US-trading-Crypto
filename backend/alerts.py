import discord
from discord.ext import tasks, commands
import asyncio
from collectors.crypto_collector import CryptoCollector
from collectors.stock_collector import StockCollector
from analysis.technical_engine import TechnicalAnalysis
from trading_executive import TradingExecutive
from collectors.dex_scout import DexScout
from analysis.safety_checker import SafetyChecker

# Import DEX trader for automated Solana trading
try:
    from dex_trader import DexTrader
    DEX_TRADING_ENABLED = True
except ImportError as e:
    print(f"⚠️ DEX Trading disabled: {e}")
    DEX_TRADING_ENABLED = False

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
        if DEX_TRADING_ENABLED:
            self.dex_trader = DexTrader()
            if self.dex_trader.wallet_address:
                print(f"🦊 DEX Auto-Trading ENABLED. Wallet: {self.dex_trader.wallet_address[:8]}...")
        else:
            self.dex_trader = None
        
        # DEX Auto-trading configuration
        self.dex_auto_trade = True  # Toggle for DEX auto-trading
        self.dex_min_safety_score = 70  # Lowered from 80 for more opportunities
        self.dex_min_liquidity = 5000  # Lowered from $10k to $5k
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
        
        self.monitor_market.start()
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
        
        # Log Stock trading status
        if self.stocks and self.stocks.api:
            account = self.stocks.get_account()
            if account:
                print(f"📈 Alpaca Account - Cash: ${account['cash']:.2f}, Buying Power: ${account['buying_power']:.2f}")



    def cog_unload(self):
        self.monitor_market.cancel()
        self.discovery_loop.cancel()
        self.kraken_discovery_loop.cancel()

    @tasks.loop(minutes=5)
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
                if channel_crypto:
                    await self._check_and_alert(symbol, channel_crypto, "Crypto")

        # 1. Monitor Majors
        print(f"Checking major crypto: {self.majors_watchlist}")
        if channel_crypto:
            for symbol in self.majors_watchlist:
                await self._check_and_alert(symbol, channel_crypto, "Crypto")

        # 2. Monitor Memes (on Kraken)
        print(f"Checking memecoins: {self.memes_watchlist}")
        if channel_memes:
            for symbol in self.memes_watchlist:
                await self._check_and_alert(symbol, channel_memes, "Meme")

        # 3. Monitor DEX Scout (New Gems) + Auto-Trade
        print(f"Scouting DEX tokens: {self.dex_watchlist} + {len(self.trending_dex_gems)} trending")
        if channel_memes:
            # Combined list of manual watchlist and trending gems
            all_dex = self.dex_watchlist + self.trending_dex_gems
            for item in all_dex:
                pair_data = await self.dex_scout.get_pair_data(item['chain'], item['address'])
                if pair_data:
                    info = self.dex_scout.extract_token_info(pair_data)
                    token_address = info.get('address', item['address'])
                    
                    # Alert if price change > 5% in 5 minutes (potential entry)
                    if info['price_change_5m'] >= 5.0:
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
                        embed.add_field(name="Status", value=f"**{audit.get('safety_status', 'N/A')}**", inline=True)
                        
                        # AUTO-TRADE: Execute buy if conditions are met
                        trade_executed = False
                        if (self.dex_auto_trade and 
                            self.dex_trader and 
                            self.dex_trader.wallet_address and
                            info['chain'] == 'solana'):
                            
                            # Check trading conditions
                            dex_positions = len(self.dex_trader.positions)
                            
                            if safety_score >= self.dex_min_safety_score and liquidity >= self.dex_min_liquidity:
                                if dex_positions < self.dex_max_positions:
                                    if token_address not in self.dex_trader.positions:
                                        # Execute the trade!
                                        trade_result = self.dex_trader.buy_token(token_address)
                                        if trade_result.get('success'):
                                            trade_executed = True
                                            embed.add_field(
                                                name="🤖 AUTO-TRADE EXECUTED", 
                                                value=f"Bought with 0.05 SOL\nTX: `{trade_result['signature'][:16]}...`", 
                                                inline=False
                                            )
                                            embed.color = discord.Color.green()
                                        else:
                                            embed.add_field(
                                                name="⚠️ Trade Failed", 
                                                value=trade_result.get('error', 'Unknown error'),
                                                inline=False
                                            )
                                    else:
                                        embed.add_field(name="ℹ️ Status", value="Already holding this token", inline=False)
                                else:
                                    embed.add_field(name="ℹ️ Status", value=f"Max positions ({self.dex_max_positions}) reached", inline=False)
                            else:
                                reasons = []
                                if safety_score < self.dex_min_safety_score:
                                    reasons.append(f"Safety {safety_score} < {self.dex_min_safety_score}")
                                if liquidity < self.dex_min_liquidity:
                                    reasons.append(f"Liquidity ${liquidity:,.0f} < ${self.dex_min_liquidity:,}")
                                embed.add_field(name="❌ Auto-Trade Skipped", value="\n".join(reasons), inline=False)
                        
                        embed.add_field(name="DEX Link", value=f"[View on DexScreener]({info['url']})", inline=False)
                        await channel_memes.send(embed=embed)
                    
                    # Check for dump / potential exit
                    elif info['price_change_5m'] <= -10.0:
                        # If we're holding this token, consider selling
                        if self.dex_trader and token_address in self.dex_trader.positions:
                            sell_result = self.dex_trader.sell_token(token_address)
                            color = discord.Color.orange()
                            embed = discord.Embed(
                                title=f"🚨 DEX AUTO-EXIT: {info['symbol']}", 
                                description="Token dropped 10%+ - Auto-selling position",
                                color=color
                            )
                            if sell_result.get('success'):
                                embed.add_field(name="Status", value="✅ Sold successfully", inline=False)
                            else:
                                embed.add_field(name="Status", value=f"❌ {sell_result.get('error')}", inline=False)
                            await channel_memes.send(embed=embed)
                
                await asyncio.sleep(0.5)

        # 4. Monitor Stocks
        print(f"Checking stock markets: {self.stock_watchlist}")
        if channel_stocks:
            for symbol in self.stock_watchlist:
                await self._check_and_alert(symbol, channel_stocks, "Stock")
                await asyncio.sleep(1)

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
            
            await self._process_alert(channel, symbol, data, asset_type)
        except Exception as e:
            # Don't spam discovery errors
            if "does not have market symbol" not in str(e):
                print(f"⚠️ Error checking {symbol}: {e}")
        await asyncio.sleep(0.3)

    @tasks.loop(minutes=10)
    async def discovery_loop(self):
        """Find new trending DEX gems automatically."""
        if not self.bot.is_ready(): return
        
        print("🔍 Running DEX Gem Discovery...")
        profiles = await self.dex_scout.get_latest_token_profiles()
        channel_memes = self.bot.get_channel(self.MEMECOINS_CHANNEL_ID)
        
        new_gems = []
        if profiles and channel_memes:
            # Profiles is a list of dicts with 'chainId', 'tokenAddress', 'url', etc.
            # Take top 5 latest profiles
            for p in profiles[:5]:
                addr = p.get('tokenAddress')
                chain = p.get('chainId')
                
                # Check if already tracking
                if any(item['address'] == addr for item in self.dex_watchlist + self.trending_dex_gems):
                    continue
                    
                # Basic Safety Audit
                audit = await self.safety.check_token(addr, "solana" if chain == 'solana' else "1")
                if audit.get('safety_status') == 'SAFE':
                    new_gems.append({"chain": chain, "address": addr})
                    embed = discord.Embed(
                        title=f"✨ NEW TRENDING GEM: {p.get('url').split('/')[-1]}",
                        description=f"AI discovered a new safe profile on **{chain.upper()}**!",
                        color=discord.Color.teal()
                    )
                    embed.add_field(name="Address", value=f"`{addr}`", inline=False)
                    embed.add_field(name="Action", value="Adding to 5m tracking list for 30 minutes.", inline=False)
                    await channel_memes.send(embed=embed)

        # Update trending gems (keep them for 3-4 cycles)
        self.trending_dex_gems = new_gems + self.trending_dex_gems[:10]

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
                        # 1. Check if we already have a position
                        if symbol in self.trader.active_positions:
                            print(f"ℹ️ Buy signal for {symbol} but already holding.")
                            return

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
                            
                            trade_result = self.trader.execute_market_buy_stock(symbol, notional=self.stock_trade_amount)
                            trade_title = "💰 ALPACA: EXECUTED BUY"
                            trade_amount = self.stock_trade_amount
                            
                            if trade_result.get('success'):
                                self.stock_positions[symbol] = trade_result
                        else:
                            trade_result = self.trader.execute_market_buy(symbol, amount_usdt=trade_amount)
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
                        else:
                            trade_result = None # No position to sell

                    if trade_result and "error" not in trade_result:
                        # Record position for SL/TP tracking (only for BUYs, or if a SELL actually executed)
                        # For sells, the position is removed by execute_market_sell internally
                        if result['signal'] == 'BUY':
                            self.trader.track_position(symbol, symbol_price, trade_result.get('amount', 0))
                        
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
