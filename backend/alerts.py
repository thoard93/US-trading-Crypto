import discord
from discord.ext import tasks, commands
import asyncio
from collectors.crypto_collector import CryptoCollector
from collectors.stock_collector import StockCollector
from analysis.technical_engine import TechnicalAnalysis
from trading_executive import TradingExecutive

class AlertSystem(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.crypto = CryptoCollector()
        self.stocks = StockCollector()
        self.analyzer = TechnicalAnalysis()
        self.trader = TradingExecutive()
        
        # User defined watchlists
        # Expanded Full-Throttle Watchlist
        self.crypto_watchlist = [
            'BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'BNB/USDT', 
            'PEPE/USDT', 'SHIB/USDT', 'DOGE/USDT', 'BONK/USDT', 'WIF/USDT'
        ]
        self.stock_watchlist = ['AAPL', 'TSLA', 'NVDA', 'AMD', 'MSFT', 'META', 'AMZN']
        
        # User defined channel IDs
        self.STOCKS_CHANNEL_ID = 1456078814567202960
        self.CRYPTO_CHANNEL_ID = 1456078864684945531
        
        self.monitor_market.start()

    def cog_unload(self):
        self.monitor_market.cancel()

    @tasks.loop(minutes=30)
    async def monitor_market(self):
        if not self.bot.is_ready():
            await self.bot.wait_until_ready()

        # 1. Monitor Crypto
        print(f"Checking crypto markets: {self.crypto_watchlist}")
        channel_crypto = self.bot.get_channel(self.CRYPTO_CHANNEL_ID)
        if channel_crypto:
            for symbol in self.crypto_watchlist:
                data = self.crypto.fetch_ohlcv(symbol, timeframe='1h', limit=100)
                if data is None:
                    print(f"❌ Failed to fetch crypto data for {symbol}")
                await self._process_alert(channel_crypto, symbol, data, "Crypto")
                await asyncio.sleep(1)

        # 2. Monitor Stocks
        print(f"Checking stock markets: {self.stock_watchlist}")
        channel_stocks = self.bot.get_channel(self.STOCKS_CHANNEL_ID)
        if channel_stocks:
            for symbol in self.stock_watchlist:
                data = self.stocks.fetch_ohlcv(symbol, timeframe='1Hour', limit=100)
                if data is None:
                    print(f"❌ Failed to fetch stock data for {symbol}")
                await self._process_alert(channel_stocks, symbol, data, "Stock")
                await asyncio.sleep(1)

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
                
                # --- AUTO-TRADING LOGIC ---
                if asset_type == "Crypto" and result['signal'] in ['BUY', 'SELL']:
                    if result['signal'] == 'BUY':
                        trade_result = self.trader.execute_market_buy(symbol)
                        trade_title = "💰 AUTO-TRADE: EXECUTED BUY"
                    else:
                        trade_result = self.trader.execute_market_sell(symbol)
                        trade_title = "💰 AUTO-TRADE: EXECUTED SELL"

                    if "error" not in trade_result:
                        trade_embed = discord.Embed(
                            title=trade_title,
                            description=f"Automated order successfully placed for **{symbol}**.",
                            color=discord.Color.dark_gold()
                        )
                        trade_embed.add_field(name="Order ID", value=trade_result.get('id', 'N/A'), inline=True)
                        trade_embed.add_field(name="Status", value="Market Order Placed", inline=True)
                        await channel.send(embed=trade_embed)
                    else:
                        print(f"❌ Auto-trade failed for {symbol}: {trade_result['error']}")
            else:
                sig = result.get('signal', 'UNKNOWN')
                print(f"ℹ️ Analysis for {symbol}: {sig} - {result.get('reason', 'N/A')}")

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
        await ctx.send("⚡ Manually triggering market scan...")
        await self.monitor_market()
        await ctx.send("✅ Scan complete.")

    @commands.command()
    async def balance(self, ctx):
        """Check Kraken USDT balance."""
        bal = self.trader.get_usdt_balance()
        await ctx.send(f"💰 **Kraken Portfolio Balance:** `{bal}` USDT")

async def setup(bot):
    await bot.add_cog(AlertSystem(bot))
