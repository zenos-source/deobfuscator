import discord
from discord.ext import commands
import aiohttp
import tempfile
import os
from pipeline import full_deobfuscation

TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='.', intents=intents)

user_scripts = {}

async def fetch_url(url):
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers={"User-Agent": "Lunr-Bot"}) as resp:
            if resp.status == 200:
                return await resp.text()
    return None

@bot.command(name='get')
async def get_script(ctx, target):
    await ctx.send(f"Fetching {target}...")
    
    if target.isdigit():
        url = f"https://raw.roblox.com/asset/?id={target}"
    elif target.startswith('http'):
        url = target
    else:
        await ctx.send("Give me a valid asset ID or URL")
        return
    
    content = await fetch_url(url)
    if not content:
        await ctx.send("Failed to fetch")
        return
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.lua', delete=False) as f:
        f.write(content)
        user_scripts[ctx.author.id] = {'path': f.name, 'content': content}
    
    preview = content[:500] + ('...' if len(content) > 500 else '')
    await ctx.send(f"Got {len(content)} bytes\n```lua\n{preview}\n```")
    await ctx.send("Use .deobf to deobfuscate")

@bot.command(name='deobf')
async def deobfuscate(ctx):
    if ctx.author.id not in user_scripts:
        await ctx.send("No script found. Use .get first")
        return
    
    await ctx.send("Deobfuscating...")
    script = user_scripts[ctx.author.id]
    
    result = await full_deobfuscation(script['content'])
    
    if len(result) > 1900:
        with tempfile.NamedTemporaryFile(mode='w', suffix='.lua', delete=False) as f:
            f.write(result)
            await ctx.send(file=discord.File(f.name, filename='deobfuscated.lua'))
        os.unlink(f.name)
    else:
        await ctx.send(f"```lua\n{result}\n```")
    
    os.unlink(script['path'])
    del user_scripts[ctx.author.id]

@bot.event
async def on_ready():
    print(f"Lunr Bot is ready - {bot.user}")

if __name__ == "__main__":
    if not TOKEN:
        print("ERROR: DISCORD_TOKEN environment variable not set")
    else:
        bot.run(TOKEN)
