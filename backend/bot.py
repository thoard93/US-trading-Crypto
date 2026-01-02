import os
import discord
from discord.ext import commands
from dotenv import load_dotenv
from collectors.crypto_collector import CryptoCollector
from analysis.technical_engine import TechnicalAnalysis
from analysis.safety_checker import SafetyChecker
from alerts import AlertSystem

# Load environment variables
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

# Initialize components
crypto = CryptoCollector()
analyzer = TechnicalAnalysis()
safety = SafetyChecker()

# Initialize bot with standard intents
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents, help_command=None)

@bot.event
async def on_ready():
    # Ensure DB is initialized before anything else
    from database import init_db
    init_db()
    
    print(f'Logged in as {bot.user.name} (ID: {bot.user.id})')
    print('US trading Crypto bot is online!')
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name="the markets 📈"))
    # Load the AlertSystem cog
    if not bot.get_cog('AlertSystem'):
        await bot.add_cog(AlertSystem(bot))
        print("Alert system loaded.")

@bot.command()
async def ping(ctx):
    """Check if the bot is alive."""
    await ctx.send(f'🏓 Pong! Latency: {round(bot.latency * 1000)}ms')

@bot.command()
async def check(ctx, address: str, chain: str = "ETH"):
    """Check token safety/rugpull risk (e.g., !check 0x... ETH)."""
    chain_id = safety.chain_map.get(chain.upper(), "1")
    await ctx.send(f"🛡️ Auditing token safety on **{chain.upper()}**... please wait.")
    
    result = await safety.check_token(address, chain_id)
    
    if "error" in result:
        await ctx.send(f"❌ Error: {result['error']}")
        return

    color = discord.Color.green()
    if result['safety_status'] == "DANGEROUS": color = discord.Color.red()
    elif result['safety_status'] == "CAUTION": color = discord.Color.gold()

    embed = discord.Embed(title=f"🛡️ Safety Audit: {result['token_name']} ({result['token_symbol']})", color=color)
    embed.add_field(name="Safety Status", value=f"**{result['safety_status']}**", inline=False)
    embed.add_field(name="Buy Tax", value=result['buy_tax'], inline=True)
    embed.add_field(name="Sell Tax", value=result['sell_tax'], inline=True)
    
    if result['risks']:
        embed.add_field(name="Identified Risks", value="\n".join(result['risks']), inline=False)
    else:
        embed.add_field(name="Identified Risks", value="✅ No major risks detected.", inline=False)

    embed.set_footer(text="Data provided by GoPlus Security API")
    await ctx.send(embed=embed)

@bot.command()
async def analyze(ctx, symbol: str):
    """Analyze a crypto pair (e.g., !analyze BTC/USDT)."""
    # Auto-format to uppercase and ensure /USDT if not provided
    symbol = symbol.strip()
    
    # Check if this is a contract address (long string)
    if len(symbol) > 30:
        await ctx.send(f"⚠️ `{symbol}` looks like a contract address. For DEX tokens, please use **`!track {symbol}`** instead!")
        return

    symbol = symbol.upper()
    if '/' not in symbol:
        symbol = f"{symbol}/USDT"

    await ctx.send(f"🔍 Analyzing **{symbol}**... please wait.")
    
    data = crypto.fetch_ohlcv(symbol, timeframe='1h', limit=100)
    if data is None:
        await ctx.send(f"❌ Error: Could not find data for `{symbol}`. Make sure it's a valid pair on Binance.")
        return

    result = analyzer.analyze_trend(data)
    
    color = discord.Color.blue()
    if result['signal'] == "BUY": color = discord.Color.green()
    elif result['signal'] == "SELL": color = discord.Color.red()

    embed = discord.Embed(title=f"📊 Market Analysis: {symbol}", color=color)
    embed.add_field(name="Current Price", value=f"${result['price']:.8f}", inline=True)
    embed.add_field(name="RSI (14)", value=result['rsi'], inline=True)
    embed.add_field(name="Signal", value=f"**{result['signal']}**", inline=False)
    embed.add_field(name="Reasoning", value=result['reason'], inline=False)
    embed.set_footer(text="Analysis based on 1h timeframe")
    
    await ctx.send(embed=embed)

@bot.command()
async def help(ctx):
    """Custom help command."""
    embed = discord.Embed(
        title="🤖 US trading Crypto Bot Help",
        description="Here are the available commands:",
        color=discord.Color.blue()
    )
    embed.add_field(name="`!ping`", value="Check bot latency.", inline=False)
    embed.add_field(name="`!analyze [symbol]`", value="Get a technical analysis report (e.g., `!analyze BTC`).", inline=False)
    embed.add_field(name="`!check [address] [chain]`", value="Scan a token for rugpull risks (Chains: `ETH`, `BSC`, `ARB`, `BASE`).", inline=False)
    embed.add_field(name="`!track [address] [chain]`", value="Monitor a DEX token by contract address (Default: `solana`).", inline=False)
    embed.add_field(name="`!scan`", value="Trigger an immediate market scan summary.", inline=False)
    embed.add_field(name="`!balance`", value="Check your Kraken USDT balance.", inline=False)
    embed.set_footer(text="Short-term trading assistant | GoPlus & CCXT")
    await ctx.send(embed=embed)

if __name__ == '__main__':
    if TOKEN:
        bot.run(TOKEN)
    else:
        print("Error: DISCORD_TOKEN not found in environment variables.")
