import discord
from discord.ext import tasks, commands
import asyncio
from collectors.crypto_collector import CryptoCollector
from collectors.stock_collector import StockCollector
from analysis.technical_engine import TechnicalAnalysis

class AlertSystem(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.crypto = CryptoCollector()
        self.stocks = StockCollector()
        self.analyzer = TechnicalAnalysis()
        
        # User defined watchlists
        self.crypto_watchlist = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'BNB/USDT']
        self.stock_watchlist = ['AAPL', 'TSLA', 'NVDA', 'AMD', 'MSFT']
        
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
                await self._process_alert(channel_crypto, symbol, data, "Crypto")
                await asyncio.sleep(1)

        # 2. Monitor Stocks
        print(f"Checking stock markets: {self.stock_watchlist}")
        channel_stocks = self.bot.get_channel(self.STOCKS_CHANNEL_ID)
        if channel_stocks:
            for symbol in self.stock_watchlist:
                data = self.stocks.fetch_ohlcv(symbol, timeframe='1Hour', limit=100)
                await self._process_alert(channel_stocks, symbol, data, "Stock")
                await asyncio.sleep(1)

    async def _process_alert(self, channel, symbol, data, asset_type):
        if data is not None:
            result = self.analyzer.analyze_trend(data)
            if result['signal'] in ['BUY', 'SELL']:
                color = discord.Color.green() if result['signal'] == 'BUY' else discord.Color.red()
                embed = discord.Embed(
                    title=f"🚀 {asset_type.upper()} ALERT: {symbol}",
                    description=f"The AI has detected a potential **{result['signal']}** opportunity!",
                    color=color
                )
                embed.add_field(name="Price", value=f"${result['price']}", inline=True)
                embed.add_field(name="RSI", value=result['rsi'], inline=True)
                embed.add_field(name="Reason", value=result['reason'], inline=False)
                embed.set_footer(text=f"Short-term {asset_type} analysis (1h timeframe)")
                await channel.send(embed=embed)

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

async def setup(bot):
    await bot.add_cog(AlertSystem(bot))
