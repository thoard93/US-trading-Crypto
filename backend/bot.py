"""
DEGEN DEX Discord Bot - Meme Token Creation Commands
Focused on launching tokens on Pump.fun with AI-generated concepts.
"""
import os
import discord
import asyncio
from discord.ext import commands
from dotenv import load_dotenv
from analysis.safety_checker import SafetyChecker
from alerts import AlertSystem
from meme_creator import MemeCreator
from dex_trader import DexTrader
from engagement_framer import EngagementFramer
import re

# Load environment variables
script_dir = os.path.dirname(os.path.abspath(__file__))
env_path = os.path.join(script_dir, '.env')
load_dotenv(env_path)
TOKEN = os.getenv('DISCORD_TOKEN', '').strip()

if TOKEN:
    print(f"🔑 Discord Token Loaded: {TOKEN[:4]}...{TOKEN[-4:]} (Length: {len(TOKEN)})")
else:
    print("❌ Critical: DISCORD_TOKEN is missing or empty!")

# Initialize components
safety = SafetyChecker()
meme_gen = MemeCreator()
trader = DexTrader()
engagement_framer = EngagementFramer(trader)

# Initialize bot with standard intents
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents, help_command=None)


class DegenBot(commands.Cog):
    """Cog wrapper for the bot to allow dependency injection."""
    
    def __init__(self, trader_instance, launcher_instance=None, hunter_instance=None):
        self.trader = trader_instance
        self.launcher = launcher_instance
        self.hunter = hunter_instance
    
    async def start(self, token):
        """Start the bot with the given token."""
        await bot.start(token)


@bot.event
async def on_ready():
    from database import init_db
    init_db()
    
    print(f'Logged in as {bot.user.name} (ID: {bot.user.id})')
    print('🚀 DEGEN DEX Token Creation Bot is online!')
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name="the charts 📈"))
    
    # Load the AlertSystem cog
    if not bot.get_cog('AlertSystem'):
        await bot.add_cog(AlertSystem(bot))
        print("✅ Alert system registered.")


@bot.command()
async def ping(ctx):
    """Check if the bot is alive."""
    await ctx.send(f'🏓 Pong! Latency: {round(bot.latency * 1000)}ms')


@bot.command()
async def check(ctx, address: str, chain: str = "SOL"):
    """Check token safety/rugpull risk (e.g., !check 0x... SOL)."""
    chain_id = safety.chain_map.get(chain.upper(), "solana")
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
async def help(ctx):
    """Custom help command."""
    embed = discord.Embed(
        title="🚀 DEGEN DEX - Token Creation Bot",
        description="Commands for launching meme tokens on Pump.fun",
        color=discord.Color.purple()
    )
    embed.add_field(name="`!ping`", value="Check bot latency.", inline=False)
    embed.add_field(name="`!check [address] [chain]`", value="Scan a token for rugpull risks.", inline=False)
    embed.add_field(name="`!trends`", value="🔥 Show current trending themes for launch ideas.", inline=False)
    embed.add_field(name="`!launch [keyword]`", value="🚀 Launch an AI-generated meme coin on pump.fun.", inline=False)
    embed.add_field(name="`!pump [mint] [rounds] [sol] [delay]`", value="📊 Run volume simulation on a token.", inline=False)
    embed.add_field(name="`!autolaunch [on/off/status]`", value="🤖 Manage the automatic trend-discovery pipeline.", inline=False)
    embed.set_footer(text="DEGEN DEX | Pump.fun Token Launcher")
    await ctx.send(embed=embed)


@bot.command()
async def trends(ctx):
    """🔥 Show current trending themes with sources (Pump.fun, Twitter, DexScreener)."""
    from trend_hunter import TrendHunter
    
    await ctx.send("🔍 Scanning all sources for trending themes...")
    
    try:
        hunter = TrendHunter()
        keywords = await asyncio.to_thread(hunter.get_trending_keywords, 15, True)
        
        if not keywords:
            await ctx.send("❌ No trending keywords found. Try again later.")
            return
        
        source_icons = {
            'pump': '🚀',
            'twitter': '🐦',
            'dex': '📊'
        }
        
        embed = discord.Embed(
            title="🔥 Trending Themes by Source",
            description="Keywords from Pump.fun 🚀, Twitter 🐦, and DexScreener 📊\nLaunch a variation with `!launch [keyword]`",
            color=discord.Color.orange()
        )
        
        formatted = []
        for item in keywords:
            icon = source_icons.get(item['source'], '❓')
            formatted.append(f"{icon} `{item['keyword']}`")
        
        col1 = formatted[:8]
        col2 = formatted[8:15]
        
        embed.add_field(name="Top Trends", value="\n".join(col1) or "None", inline=True)
        embed.add_field(name="More Trends", value="\n".join(col2) or "None", inline=True)
        
        embed.set_footer(text="🚀 = Pump.fun | 🐦 = Twitter | 📊 = DexScreener")
        await ctx.send(embed=embed)
        
    except Exception as e:
        await ctx.send(f"❌ Error scanning trends: {e}")


@bot.command()
async def launch(ctx, *, keyword: str):
    """🚀 Launch an AI-generated meme coin on pump.fun (e.g., !launch Blue Whale)."""
    print(f"🚀 Launch command called in channel ID: {ctx.channel.id}")
        
    # Parse optional SOL amount from end of keyword
    sol_amount = 0.01
    parts = keyword.rsplit(' ', 1)
    if len(parts) > 1:
        try:
            potential_amount = float(parts[1])
            if 0.001 <= potential_amount <= 2.0:
                sol_amount = potential_amount
                keyword = parts[0]
                print(f"🚀 BUNDLE: Using manual volume: {sol_amount} SOL")
        except ValueError:
            pass

    await ctx.send(f"🧠 **AI Strategist**: Analyzing '{keyword}' for viral potential (Volume: {sol_amount} SOL)... 🧊")
    
    # Generate Meme Concept & Logo
    result = await asyncio.to_thread(meme_gen.create_full_meme, keyword)
    
    if not result:
        await ctx.send("❌ Error: AI Brain failed to generate a viral concept. Check logs.")
        return
        
    embed = discord.Embed(title=f"🚀 Viral Intent Detected: {result['name']} ({result['ticker']})", color=discord.Color.gold())
    embed.add_field(name="Concept", value=result['description'], inline=False)
    
    if result.get('image_url'):
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
    
    # Determine social links
    fixed_twitter = os.getenv('AUTO_LAUNCH_X_HANDLE', '')
    fixed_tg = os.getenv('AUTO_LAUNCH_TG_LINK', '')
    
    clean_name = re.sub(r'[^a-zA-Z0-9]', '', result['name']).lower()
    twitter_link = fixed_twitter if fixed_twitter else f"https://x.com/{clean_name}_sol"
    tg_link = fixed_tg if fixed_tg else f"https://t.me/{clean_name}_portal"
    
    # Launch on-chain
    launch_res = await asyncio.to_thread(
        trader.create_pump_token,
        name=result['name'],
        symbol=result['ticker'],
        description=result['description'],
        image_url=result['image_url'],
        sol_buy_amount=sol_amount,
        use_jito=False,
        twitter=twitter_link,
        telegram=tg_link,
        website=''
    )
    
    if launch_res.get('success'):
        success_embed = discord.Embed(title="🚀 COIN IS LIVE ON PUMP.FUN!", color=discord.Color.green())
        success_embed.add_field(name="Mint Address", value=f"`{launch_res['mint']}`", inline=False)
        success_embed.add_field(name="Solscan", value=f"[View Transaction](https://solscan.io/tx/{launch_res['signature']})", inline=False)
        success_embed.add_field(name="Pump.fun", value=f"[View on Pump.fun](https://pump.fun/{launch_res['mint']})", inline=False)
        await ctx.send(embed=success_embed)
        
        # Trigger Engagement Farming
        await ctx.send("📢 **Social Hype Engine** starting... Building community presence.")
        asyncio.create_task(engagement_framer.farm_engagement(launch_res['mint'], count=3))
        
        # Trigger Volume Simulation (multi-wallet, same as auto-launcher)
        # Get all wallets except the creator (main wallet for manual launches)
        import random
        
        all_keys = []
        if hasattr(trader, 'wallet_manager') and trader.wallet_manager:
            all_keys = trader.wallet_manager.get_all_keys() or []
        
        # For manual launches, creator is the main wallet - filter it out
        main_key = trader.wallet_manager.get_main_key() if hasattr(trader, 'wallet_manager') and trader.wallet_manager else None
        sim_wallets = [k for k in all_keys if k != main_key] if main_key else all_keys
        
        if not sim_wallets:
            # Fallback: at least use one wallet
            await ctx.send("📊 **Volume Simulation** starting with 1 wallet...")
            async def discord_vol_callback(msg):
                try:
                    await ctx.send(f"📊 {msg}")
                except:
                    pass
            asyncio.create_task(trader.simulate_volume(
                launch_res['mint'],
                rounds=10,
                sol_per_round=0.01,
                delay_seconds=30,
                callback=discord_vol_callback,
                moon_bias=0.95
            ))
        else:
            await ctx.send(f"📊 **Volume Simulation** starting with {len(sim_wallets)} wallets...")
            
            for wallet_idx, wallet_key in enumerate(sim_wallets):
                wallet_label = f"W{wallet_idx+1}"
                
                # Only W1 sends Discord updates to avoid spam
                def make_callback(label, send_to_discord):
                    if send_to_discord:
                        async def cb(msg):
                            try:
                                await ctx.send(f"📊 [{label}] {msg}")
                            except:
                                pass
                        return cb
                    return None
                
                # Randomize moon_bias per wallet for organic look (88-96%)
                wallet_moon_bias = round(random.uniform(0.88, 0.96), 2)
                send_discord = (wallet_idx == 0)
                
                asyncio.create_task(trader.simulate_volume(
                    launch_res['mint'],
                    rounds=10,
                    sol_per_round=0.01,
                    delay_seconds=30,
                    callback=make_callback(wallet_label, send_discord),
                    moon_bias=wallet_moon_bias,
                    ticker=f"{result['ticker']}-{wallet_label}",
                    payer_key=wallet_key
                ))
        
        # Record to database
        try:
            from database import SessionLocal
            from models import LaunchedKeyword
            from datetime import datetime
            
            db = SessionLocal()
            new_launch = LaunchedKeyword(
                keyword=keyword.upper(),
                name=result['name'],
                symbol=result['ticker'],
                mint_address=launch_res['mint'],
                launched_at=datetime.utcnow()
            )
            db.add(new_launch)
            db.commit()
            db.close()
            print(f"💾 Saved manual launch for {result['name']} to DB.")
        except Exception as db_err:
            print(f"⚠️ Failed to save manual launch to DB: {db_err}")
    else:
        await ctx.send(f"❌ **LAUNCH FAILED**: {launch_res.get('error', 'Unknown Error')}")


@bot.command()
async def pump(ctx, mint_address: str, rounds: int = 10, sol_per_round: float = 0.01, delay: int = 30, bias: float = 0.95):
    """📊 Run volume simulation on existing token with Moon Bias."""
    if len(mint_address) < 32 or len(mint_address) > 50:
        await ctx.send("❌ Invalid mint address. Use the full token address from Pump.fun.")
        return
    
    if rounds < 1 or rounds > 20:
        await ctx.send("❌ Rounds must be between 1 and 20.")
        return
    if sol_per_round < 0.005 or sol_per_round > 0.5:
        await ctx.send("❌ SOL per round must be between 0.005 and 0.5.")
        return
    
    total_cost = rounds * sol_per_round
    await ctx.send(
        f"🔥 **VOLUME SIMULATION** starting on `{mint_address[:12]}...`\n"
        f"📊 **Config**: {rounds} rounds × {sol_per_round} SOL = ~{total_cost:.3f} SOL total\n"
        f"⏱️ **Delay**: {delay}s between trades\n"
        f"_Watch the logs for real-time updates..._"
    )
    
    async def discord_callback(msg):
        await ctx.send(f"📊 {msg}")
    
    try:
        result = await trader.simulate_volume(
            mint_address,
            rounds=rounds,
            sol_per_round=sol_per_round,
            delay_seconds=delay,
            callback=discord_callback,
            moon_bias=bias
        )
        
        if result.get('success'):
            await ctx.send(
                f"✅ **VOLUME SIMULATION COMPLETE!**\n"
                f"🛒 {result['buys']} buys | 🏷️ {result['sells']} sells\n"
                f"🔗 [View on Pump.fun](https://pump.fun/{mint_address})"
            )
        else:
            await ctx.send(f"⚠️ Simulation ended with issues. Check logs.")
    except Exception as e:
        await ctx.send(f"❌ Simulation error: {e}")


async def start_services():
    """Start the Discord bot and Webhook Listener together."""
    import uvicorn
    from webhook_listener import app, set_bot_instance
    
    set_bot_instance(bot)
    
    port = int(os.getenv("PORT", 8000))
    config = uvicorn.Config(app, host="0.0.0.0", port=port, log_level="info")
    server = uvicorn.Server(config)
    
    print(f"📡 Webhook Listener starting on port {port}...")
    
    await asyncio.gather(
        bot.start(TOKEN),
        server.serve()
    )


if __name__ == '__main__':
    if TOKEN:
        try:
            asyncio.run(start_services())
        except KeyboardInterrupt:
            pass
    else:
        print("Error: DISCORD_TOKEN not found in environment variables.")
