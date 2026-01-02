import discord
from discord.ext import tasks, commands
import asyncio
from collectors.crypto_collector import CryptoCollector
from collectors.stock_collector import StockCollector
from analysis.technical_engine import TechnicalAnalysis
from trading_executive import TradingExecutive
from collectors.dex_scout import DexScout
from analysis.safety_checker import SafetyChecker

class AlertSystem(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.crypto = CryptoCollector()
        self.stocks = StockCollector()
        self.analyzer = TechnicalAnalysis()
        self.trader = TradingExecutive()
        self.dex_scout = DexScout()
        self.safety = SafetyChecker()
        
        # User defined watchlists
        self.majors_watchlist = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'BNB/USDT']
        self.memes_watchlist = ['PEPE/USDT', 'SHIB/USDT', 'DOGE/USDT', 'BONK/USDT', 'WIF/USDT']
        self.dex_watchlist = [
            {"chain": "solana", "address": "HBoNJ5v8g71s2boRivrHnfSB5MVPLDHHyVjruPfhGkvL"} # Purple Pepe
        ]
        self.stock_watchlist = ['AAPL', 'TSLA', 'NVDA', 'AMD', 'MSFT', 'META', 'AMZN']
        
        # User defined channel IDs
        self.STOCKS_CHANNEL_ID = 1456078814567202960
        self.CRYPTO_CHANNEL_ID = 1456078864684945531
        self.MEMECOINS_CHANNEL_ID = 1456439911896060028
        
        self.trending_dex_gems = [] # Temporarily tracked trending gems
        
        self.monitor_market.start()
        self.discovery_loop.start()
        self.kraken_discovery_loop.start()

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

        # 3. Monitor DEX Scout (New Gems)
        print(f"Scouting DEX tokens: {self.dex_watchlist} + {len(self.trending_dex_gems)} trending")
        if channel_memes:
            # Combined list of manual watchlist and trending gems
            all_dex = self.dex_watchlist + self.trending_dex_gems
            for item in all_dex:
                pair_data = await self.dex_scout.get_pair_data(item['chain'], item['address'])
                if pair_data:
                    info = self.dex_scout.extract_token_info(pair_data)
                    # Alert if price change > 5% in 5 minutes
                    if abs(info['price_change_5m']) >= 5.0:
                        # Safety Audit
                        audit = await self.safety.check_token(info['address'], "solana" if info['chain'] == 'solana' else "1")
                        
                        color = discord.Color.purple() if info['price_change_5m'] > 0 else discord.Color.dark_red()
                        trend = "🚀 PUMPING" if info['price_change_5m'] > 0 else "📉 DUMPING"
                        
                        embed = discord.Embed(title=f"🟣 DEX GEM {trend}: {info['symbol']} ({info['chain'].upper()})", color=color)
                        embed.add_field(name="Price USD", value=f"${info['price_usd']:.8f}", inline=True)
                        embed.add_field(name="5m Change", value=f"{info['price_change_5m']}%", inline=True)
                        embed.add_field(name="Liquidity", value=f"${info['liquidity_usd']:,.0f}", inline=True)
                        embed.add_field(name="Safety Status", value=f"**{audit.get('safety_status', 'N/A')}**", inline=False)
                        embed.add_field(name="DEX Link", value=f"[View on DexScreener]({info['url']})", inline=False)
                        
                        await channel_memes.send(embed=embed)
                await asyncio.sleep(0.5)

        # 4. Monitor Stocks
        print(f"Checking stock markets: {self.stock_watchlist}")
        if channel_stocks:
            for symbol in self.stock_watchlist:
                data = self.stocks.fetch_ohlcv(symbol, timeframe='1Hour', limit=100)
                if data is not None:
                    await self._process_alert(channel_stocks, symbol, data, "Stock")
                await asyncio.sleep(1)

    async def _check_and_alert(self, symbol, channel, asset_type):
        """Helper to fetch data, check exits, and process alerts."""
        data = self.crypto.fetch_ohlcv(symbol, timeframe='1h', limit=100)
        if data is None:
            print(f"❌ Failed to fetch data for {symbol}")
            return

        current_price = data.iloc[-1]['close']
        p_str = f"{current_price:.8f}" if current_price < 1.0 else f"{current_price:.2f}"
        
        # Stop-Loss / Take-Profit
        exit_reason = self.trader.check_exit_conditions(symbol, current_price)
        if exit_reason:
            exit_res = self.trader.execute_market_sell(symbol)
            if "error" not in exit_res:
                embed = discord.Embed(
                    title=f"🚨 AUTO-EXIT: {exit_reason}",
                    description=f"Closed position for **{symbol}** at ${p_str}",
                    color=discord.Color.orange()
                )
                await channel.send(embed=embed)
                if symbol in self.trader.active_positions:
                    del self.trader.active_positions[symbol]

        await self._process_alert(channel, symbol, data, asset_type)
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
            # Fetch all tickers from Kraken
            tickers = self.crypto.exchange.fetch_tickers()
            usdt_tickers = []
            
            for symbol, ticker in tickers.items():
                if '/USDT' in symbol and ticker.get('quoteVolume'):
                    usdt_tickers.append({
                        'symbol': symbol,
                        'volume': float(ticker.get('quoteVolume', 0)),
                        'price': float(ticker.get('last', 0))
                    })
            
            # Sort by volume (Top 25)
            sorted_tickers = sorted(usdt_tickers, key=lambda x: x['volume'], reverse=True)[:25]
            
            new_majors = []
            new_memes = []
            
            for t in sorted_tickers:
                s = t['symbol']
                p = t['price']
                
                # Exclude sub-pennies/memes from majors
                if p > 1.0 and s not in new_majors:
                    new_majors.append(s)
                elif p <= 1.0 and s not in new_memes:
                    new_memes.append(s)
            
            # Static list + Top discovered ones
            # We keep our core list and append new high volume ones
            core_majors = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'BNB/USDT']
            core_memes = ['PEPE/USDT', 'SHIB/USDT', 'DOGE/USDT', 'BONK/USDT', 'WIF/USDT']
            
            self.majors_watchlist = sorted(list(set(core_majors + new_majors[:6])))
            self.memes_watchlist = sorted(list(set(core_memes + new_memes[:10])))
            
            print(f"✅ Kraken Watchlist Updated. Majors: {len(self.majors_watchlist)}, Memes: {len(self.memes_watchlist)}")
            
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
                if asset_type in ["Crypto", "Meme"] and result['signal'] in ['BUY', 'SELL']:
                    symbol_price = result['price']
                    trade_result = None
                    
                    # Target memes or coins under $1 for "Micro-Scalping"
                    if asset_type == "Meme" or symbol_price < 1.0:
                        trade_amount = 2.0  # Scalp with $2 for high-volatility micro-caps
                        scalp_mode = True
                    else:
                        trade_amount = 10.0 # Standard trade for major coins
                        scalp_mode = False

                    if result['signal'] == 'BUY':
                        # Automated Safety Audit for small coins
                        if symbol_price < 1.0:
                            await channel.send(f"🛡️ **Scalp Safety Check:** Auditing `{symbol}` before entry...")
                            # Note: Real rug-pull check usually needs contract address. 
                            # For Kraken-listed tokens, we check for high RSI/Volatility instead.
                            # We will add a placeholder for address-based audit if available.
                        
                        trade_result = self.trader.execute_market_buy(symbol, amount_usdt=trade_amount)
                        trade_title = "💰 SCALP: EXECUTED BUY" if scalp_mode else "💰 AUTO-TRADE: EXECUTED BUY"
                    else:
                        trade_result = self.trader.execute_market_sell(symbol)
                        trade_title = "📉 SCALP: EXECUTED SELL" if scalp_mode else "📉 AUTO-TRADE: EXECUTED SELL"

                    if "error" not in trade_result:
                        # Record position for SL/TP tracking
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
    async def add_watchlist(self, ctx, symbol: str, asset_type: str = "crypto"):
        """Add to watchlist. Usage: !add_watchlist BTC crypto OR !add_watchlist TSLA stock"""
        symbol = symbol.upper()
        if asset_type.lower() == "crypto":
            if '/' not in symbol: symbol = f"{symbol}/USDT"
            if symbol not in self.crypto_watchlist:
                self.crypto_watchlist.append(symbol)
                await ctx.send(f"✅ Added {symbol} to Crypto watchlist.")
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
