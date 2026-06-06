import discord
from discord.ext import commands
import aiohttp
import tempfile
import os
import re
import sys

print(f"Python version: {sys.version}")
print("Starting Lunr Bot...")

TOKEN = os.getenv("DISCORD_TOKEN")

if not TOKEN:
    print("ERROR: DISCORD_TOKEN not set")
    sys.exit(1)

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

def decode_hex(content):
    result = content
    hex_pattern = r'["\']([0-9a-fA-F]{20,})["\']'
    for match in re.finditer(hex_pattern, content):
        hex_str = match.group(1)
        try:
            decoded = bytes.fromhex(hex_str).decode('utf-8', errors='ignore')
            result = result.replace(f'"{hex_str}"', f'--[[hex decoded]]\n"{decoded}"')
        except:
            pass
    return result

async def resolve_loadstrings(content, depth=0):
    if depth > 3:
        return content
    patterns = [
        r'loadstring\(game:HttpGet\(["\']([^"\']+)["\']\)\)',
    ]
    async with aiohttp.ClientSession() as session:
        for pattern in patterns:
            matches = re.findall(pattern, content)
            for url in matches:
                try:
                    async with session.get(url, timeout=10) as resp:
                        if resp.status == 200:
                            fetched = await resp.text()
                            content = content.replace(
                                f'loadstring(game:HttpGet("{url}"))',
                                f'--[[ from {url} ]]\n{fetched}\n--[[ end ]]'
                            )
                            content = await resolve_loadstrings(content, depth + 1)
                except:
                    pass
    return content

@bot.command(name='get')
async def get_script(ctx, target):
    await ctx.send(f"🔍 Fetching `{target}`...")
    
    if target.isdigit():
        url = f"https://raw.roblox.com/asset/?id={target}"
    elif target.startswith('http'):
        url = target
    else:
        await ctx.send("❌ Give me asset ID or URL")
        return
    
    content = await fetch_url(url)
    if not content:
        await ctx.send("❌ Failed to fetch")
        return
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.lua', delete=False) as f:
        f.write(content)
        user_scripts[ctx.author.id] = {'path': f.name, 'content': content}
    
    preview = content[:400] + ('...' if len(content) > 400 else '')
    await ctx.send(f"✅ Got {len(content)} bytes\n```lua\n{preview}\n```")
    await ctx.send("🔧 Use `.deobf` to deobfuscate")

@bot.command(name='deobf')
async def deobfuscate(ctx):
    if ctx.author.id not in user_scripts:
        await ctx.send("❌ No script. Use `.get` first")
        return
    
    await ctx.send("🔧 Deobfuscating...")
    script = user_scripts[ctx.author.id]
    content = script['content']
    
    content = decode_hex(content)
    content = await resolve_loadstrings(content)
    
    if len(content) > 1900:
        with tempfile.NamedTemporaryFile(mode='w', suffix='.lua', delete=False) as f:
            f.write(content)
            await ctx.send(file=discord.File(f.name, filename='deobfuscated.lua'))
        os.unlink(f.name)
    else:
        await ctx.send(f"```lua\n{content}\n```")
    
    os.unlink(script['path'])
    del user_scripts[ctx.author.id]

@bot.event
async def on_ready():
    print(f"✅ Lunr Bot ready - {bot.user}")
    print(f"📡 Invite: https://discord.com/oauth2/authorize?client_id={bot.user.id}&permissions=274877958144&scope=bot")

if __name__ == "__main__":
    bot.run(TOKEN)
