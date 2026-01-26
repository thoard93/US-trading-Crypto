import os
import discord
import asyncio
from discord.ext import commands
from dotenv import load_dotenv
from collectors.crypto_collector import CryptoCollector
# from analysis.technical_engine import TechnicalAnalysis  # Disabled: pandas_ta not compatible with Python 3.11
from analysis.safety_checker import SafetyChecker
from alerts import AlertSystem
from meme_creator import MemeCreator
from dex_trader import DexTrader

# Load environment variables (Robust pathing)
script_dir = os.path.dirname(os.path.abspath(__file__))
env_path = os.path.join(script_dir, '.env')
load_dotenv(env_path)
TOKEN = os.getenv('DISCORD_TOKEN', '').strip()

# DEBUG: Print token info (Safe)
if TOKEN:
    print(f"🔑 Discord Token Loaded: {TOKEN[:4]}...{TOKEN[-4:]} (Length: {len(TOKEN)})")
else:
    print("❌ Critical: DISCORD_TOKEN is missing or empty!")

# Initialize components
crypto = CryptoCollector()
# analyzer = TechnicalAnalysis()  # Disabled: pandas_ta not compatible with Python 3.11
safety = SafetyChecker()
meme_gen = MemeCreator()
trader = DexTrader()

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
        # Instantiate FIRST, then add. 
        # Since AlertSystem now has a non-blocking cog_load, this is safe.
        await bot.add_cog(AlertSystem(bot))
        print("✅ Alert system registered.")
        # Diagnostic: List all loaded cogs to verify registration
        cogs = list(bot.cogs.keys())
        print(f"📦 Loaded Cogs: {cogs}")

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
    # TechnicalAnalysis disabled due to pandas_ta incompatibility with Python 3.11
    await ctx.send(f"⚠️ The `!analyze` command is temporarily disabled on the VPS. Use DEX tracking instead!")
    return
    
    # Original code commented out:
    # data = crypto.fetch_ohlcv(symbol, timeframe='1h', limit=100)
    # if data is None:
    #     await ctx.send(f"❌ Error: Could not find data for `{symbol}`. Make sure it's a valid pair on Binance.")
    #     return
    #
    # result = analyzer.analyze_trend(data)
    # 
    # color = discord.Color.blue()
    # if result['signal'] == "BUY": color = discord.Color.green()
    # elif result['signal'] == "SELL": color = discord.Color.red()
    #
    # embed = discord.Embed(title=f"📊 Market Analysis: {symbol}", color=color)
    # embed.add_field(name="Current Price", value=f"${result['price']:.8f}", inline=True)
    # embed.add_field(name="RSI (14)", value=result['rsi'], inline=True)
    # embed.add_field(name="Signal", value=f"**{result['signal']}**", inline=False)
    # embed.add_field(name="Reasoning", value=result['reason'], inline=False)
    # embed.set_footer(text="Analysis based on 1h timeframe")
    # 
    # await ctx.send(embed=embed)

@bot.command()
async def help(ctx):
    """Custom help command."""
    # Only respond in trading channels
    TRADING_CHANNEL_IDS = [1456078814567202960, 1456078864684945531, 1456439911896060028]
    if ctx.channel.id not in TRADING_CHANNEL_IDS:
        return  # Silently ignore in non-trading channels
    
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
    embed.add_field(name="`!launch [keyword]`", value="🚀 Launch an AI-generated meme coin on pump.fun (e.g., `!launch Blue Whale`).", inline=False)
    embed.add_field(name="`!autolaunch [on/off/status]`", value="🤖 Manage the automatic trend-discovery and launch pipeline.", inline=False)
    embed.set_footer(text="Short-term trading assistant | GoPlus & CCXT")
    await ctx.send(embed=embed)

@bot.command()
async def launch(ctx, *, keyword: str):
    """🚀 Launch an AI-generated meme coin on pump.fun (e.g., !launch Blue Whale)."""
    # Log channel ID for debugging
    print(f"🚀 Launch command called in channel ID: {ctx.channel.id}")
        
    # Parse optional SOL amount from end of keyword (e.g. !launch MyCoin 0.05)
    sol_amount = 0.01  # Default
    parts = keyword.rsplit(' ', 1)
    if len(parts) > 1:
        try:
            potential_amount = float(parts[1])
            if 0.001 <= potential_amount <= 2.0: # Cap at 2 SOL for safety
                sol_amount = potential_amount
                keyword = parts[0]
                print(f"🚀 BUNDLE: Using manual volume: {sol_amount} SOL")
        except ValueError:
            pass # Keep original keyword and default amount

    await ctx.send(f"🧠 **AI Strategist**: Analyzing '{keyword}' for viral potential (Volume: {sol_amount} SOL)... 🧊")
    
    # 1. Generate Meme Concept & Logo
    result = await asyncio.to_thread(meme_gen.create_full_meme, keyword)
    
    if not result:
        await ctx.send("❌ Error: AI Brain failed to generate a viral concept. Check logs.")
        return
        
    embed = discord.Embed(title=f"🚀 Viral Intent Detected: {result['name']} ({result['ticker']})", color=discord.Color.gold())
    embed.add_field(name="Concept", value=result['description'], inline=False)
    embed.set_image(url=result['image_url'])
    await ctx.send(embed=embed)
    
    confirm_msg = await ctx.send(f"⚠️ **CONFIRMATION REQUIRED**: Do you want to launch this coin on pump.fun?\n🔥 **Volume Seed**: {sol_amount} SOL\nReact with ✅ to deploy.")
    await confirm_msg.add_reaction("✅")
    
    def check(reaction, user):
        return user == ctx.author and str(reaction.emoji) == "✅" and reaction.message.id == confirm_msg.id
        
    try:
        reaction, user = await bot.wait_for('reaction_add', timeout=60.0, check=check)
    except asyncio.TimeoutError:
        await ctx.send("⏳ Launch cancelled (Timeout).")
        return
        
    await ctx.send("⚡ **DEPLOYING TO SOLANA MAINNET**... Hold your breath.")
    
    # 2. Launch on-chain
    launch_res = await asyncio.to_thread(
        trader.create_pump_token,
        name=result['name'],
        symbol=result['ticker'],
        description=result['description'],
        image_url=result['image_url'],
        sol_buy_amount=sol_amount
    )
    
    if launch_res.get('success'):
        success_embed = discord.Embed(title="🚀 COIN IS LIVE ON PUMP.FUN!", color=discord.Color.green())
        success_embed.add_field(name="Mint Address", value=f"`{launch_res['mint']}`", inline=False)
        success_embed.add_field(name="Solscan", value=f"[View Transaction](https://solscan.io/tx/{launch_res['signature']})", inline=False)
        success_embed.add_field(name="Pump.fun", value=f"[View on Pump.fun](https://pump.fun/{launch_res['mint']})", inline=False)
        await ctx.send(embed=success_embed)
    else:
        await ctx.send(f"❌ **LAUNCH FAILED**: {launch_res.get('error', 'Unknown Error')}")

async def start_services():
    # 1. Start Webhook Listener (FastAPI)
    import uvicorn
    from webhook_listener import app, set_bot_instance
    
    # Link bot to listener for signal dispatch
    set_bot_instance(bot)
    
    # Configure Server
    # Render provides PORT environment variable
    port = int(os.getenv("PORT", 8000))
    config = uvicorn.Config(app, host="0.0.0.0", port=port, log_level="info")
    server = uvicorn.Server(config)
    
    print(f"📡 Webhook Listener starting on port {port}...")
    
    # 2. Run both
    await asyncio.gather(
        bot.start(TOKEN),
        server.serve()
    )

if __name__ == '__main__':
    if TOKEN:
        try:
            import asyncio
            asyncio.run(start_services())
        except KeyboardInterrupt:
            pass
    else:
        print("Error: DISCORD_TOKEN not found in environment variables.")
