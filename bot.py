import discord
from discord.ext import commands
import aiohttp
import tempfile
import os
import re
import asyncio
import json

TOKEN = os.getenv("DISCORD_TOKEN")

if not TOKEN:
    print("ERROR: DISCORD_TOKEN not set")
    exit(1)

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='.', intents=intents)

user_scripts = {}

async def fetch_url(url):
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, timeout=10) as resp:
                if resp.status == 200:
                    return await resp.text()
        except:
            pass
    return None

async def fetch_script(target):
    if target.startswith('http'):
        return await fetch_url(target)
    if target.isdigit():
        return await fetch_url(f'https://raw.roblox.com/asset/?id={target}')
    return None

def detect_obfuscator(content):
    if 'wearedevs.net/obfuscator' in content:
        return 'WeAreDevs'
    if 'moonsec' in content.lower():
        return 'MoonSec'
    if re.search(r'local d = \{\\d{3}', content):
        return 'WeAreDevs'
    return 'Unknown'

def deobf_wearedevs(content):
    """Decode WeAreDevs obfuscated scripts"""
    result = content
    
    # Decode octal
    result = re.sub(r'\\(\d{3})', lambda m: chr(int(m.group(1), 8)), result)
    
    # Decode hex
    result = re.sub(r'\\x([0-9a-fA-F]{2})', lambda m: chr(int(m.group(1), 16)), result)
    
    # Decode string.char
    result = re.sub(r'string\.char\(([^)]+)\)', 
                    lambda m: ''.join(chr(int(x.strip())) for x in m.group(1).split(',')), 
                    result)
    
    # Extract string table
    table_match = re.search(r'local d = \{(.*?)\};', result, re.DOTALL)
    if table_match:
        strings = re.findall(r'"((?:\\\d{3}|[^"])*)"', table_match.group(1))
        for i, s in enumerate(strings, 1):
            decoded = re.sub(r'\\(\d{3})', lambda m: chr(int(m.group(1), 8)), s)
            result = re.sub(r'd\[' + str(i) + r'\]', f'"{decoded}"', result)
            result = re.sub(r'd\s*\[\s*' + str(i) + r'\s*\]', f'"{decoded}"', result)
        
        result = re.sub(r'local d = \{.*?\};', '', result, flags=re.DOTALL)
    
    # Clean up
    result = re.sub(r'\n\s*\n', '\n', result)
    result = result.strip()
    
    return result

async def deobf_moonsec_api(content):
    """Use free deobfuscation API for MoonSec"""
    # Try multiple free APIs
    apis = [
        {
            "url": "https://de4lua.vercel.app/api/deobfuscate",
            "method": "POST",
            "data": {"code": content[:5000]}  # Limit length
        },
        {
            "url": "https://luadeobfuscator.herokuapp.com/deobfuscate",
            "method": "POST", 
            "data": {"code": content[:5000]}
        }
    ]
    
    for api in apis:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(api["url"], json=api["data"], timeout=15) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data.get("result") or data.get("deobfuscated"):
                            return data.get("result") or data.get("deobfuscated")
        except:
            pass
    
    return None

@bot.command()
async def get(ctx, target):
    await ctx.send("🔍 Fetching...")
    content = await fetch_script(target)
    
    if not content:
        await ctx.send("❌ Failed to fetch script")
        return
    
    user_scripts[ctx.author.id] = content
    obf_type = detect_obfuscator(content)
    preview = content[:300] + ('...' if len(content) > 300 else '')
    
    await ctx.send(f"✅ {len(content)} bytes | **{obf_type}**")
    await ctx.send(f"```lua\n{preview}\n```")
    await ctx.send("🔧 Use `.deobf` to deobfuscate")

@bot.command()
async def deobf(ctx):
    if ctx.author.id not in user_scripts:
        await ctx.send("❌ No script. Use `.get` first")
        return
    
    msg = await ctx.send("🔧 Deobfuscating...")
    content = user_scripts[ctx.author.id]
    obf_type = detect_obfuscator(content)
    
    result = None
    
    if obf_type == 'WeAreDevs':
        result = deobf_wearedevs(content)
        await msg.edit(content="✅ WeAreDevs deobfuscation complete!")
    elif obf_type == 'MoonSec':
        await msg.edit(content="🔧 MoonSec detected - trying online deobfuscator...")
        result = await deobf_moonsec_api(content)
        if result:
            await msg.edit(content="✅ MoonSec deobfuscation complete!")
        else:
            await msg.edit(content="⚠️ Online deobfuscation failed. MoonSec requires local devirtualization.\n\nTry using Larry Dumper locally:\n```bash\nlua grimhub.lua input.lua output.lua\n```")
            return
    else:
        result = deobf_wearedevs(content)
    
    if not result or result == content or len(result) < 100:
        await msg.edit(content="⚠️ Could not deobfuscate. The script may use advanced protection.")
        return
    
    if len(result) > 1900:
        with tempfile.NamedTemporaryFile(mode='w', suffix='.lua', delete=False) as f:
            f.write(result)
            await ctx.send(file=discord.File(f.name, filename='deobfuscated.lua'))
        os.unlink(f.name)
    else:
        await ctx.send(f"```lua\n{result}\n```")
    
    await msg.delete()
    del user_scripts[ctx.author.id]

@bot.command()
async def detect(ctx):
    if ctx.author.id not in user_scripts:
        await ctx.send("❌ No script. Use `.get` first")
        return
    
    content = user_scripts[ctx.author.id]
    obf_type = detect_obfuscator(content)
    await ctx.send(f"🔍 **{obf_type}**")

@bot.event
async def on_ready():
    await bot.change_presence(status=discord.Status.online)
    print(f"✅ Lunr Bot ready - {bot.user}")
    print(f"📡 Commands: .get, .deobf, .detect")

bot.run(TOKEN)
