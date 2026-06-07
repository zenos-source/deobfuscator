import discord
from discord.ext import commands
import aiohttp
import tempfile
import os
import re
import asyncio

TOKEN = os.getenv("DISCORD_TOKEN")

if not TOKEN:
    print("ERROR: DISCORD_TOKEN not set")
    exit(1)

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='.', intents=intents)

user_scripts = {}

# ============================================================
# WEAREDEVS DEOBFUSCATOR
# ============================================================

def decode_wearedevs(content):
    """Properly decode WeAreDevs obfuscated scripts"""
    result = content
    
    # Step 1: Decode octal sequences \123
    result = re.sub(r'\\(\d{3})', lambda m: chr(int(m.group(1), 8)), result)
    
    # Step 2: Decode hex sequences \x48
    result = re.sub(r'\\x([0-9a-fA-F]{2})', lambda m: chr(int(m.group(1), 16)), result)
    
    # Step 3: Decode string.char() calls
    result = re.sub(r'string\.char\(([^)]+)\)', lambda m: ''.join(chr(int(x.strip())) for x in m.group(1).split(',')), result)
    
    # Step 4: Extract the string table and replace references
    table_match = re.search(r'local d = \{(.*?)\};', result, re.DOTALL)
    if table_match:
        table_content = table_match.group(1)
        # Find all quoted strings in the table
        strings = re.findall(r'"((?:\\\d{3}|[^"])*)"', table_content)
        
        decoded_strings = []
        for s in strings:
            # Decode each string
            decoded = re.sub(r'\\(\d{3})', lambda m: chr(int(m.group(1), 8)), s)
            decoded_strings.append(decoded)
        
        # Replace d[index] with actual strings
        for i, decoded in enumerate(decoded_strings, 1):
            result = re.sub(r'd\[%d\]' % i, f'"{decoded}"', result)
            result = re.sub(r'd\s*\[\s*%d\s*\]' % i, f'"{decoded}"', result)
        
        # Remove the table definition
        result = re.sub(r'local d = \{.*?\};', '', result, flags=re.DOTALL)
    
    # Step 5: Clean up
    result = re.sub(r'\n\s*\n', '\n', result)
    result = result.strip()
    
    return result

def detect_obfuscator(content):
    if 'wearedevs.net/obfuscator' in content or re.search(r'local d = \{["\\]', content):
        return 'WeAreDevs'
    if 'moonsec' in content.lower():
        return 'MoonSec'
    if 'ironbrew' in content.lower():
        return 'IronBrew'
    return 'Unknown'

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

# ============================================================
# DISCORD COMMANDS
# ============================================================

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
    
    await ctx.send("🔧 Deobfuscating...")
    content = user_scripts[ctx.author.id]
    obf_type = detect_obfuscator(content)
    
    if obf_type == 'WeAreDevs':
        result = decode_wearedevs(content)
    else:
        result = content
        await ctx.send(f"⚠️ Unsupported obfuscator: {obf_type}")
        return
    
    if result == content:
        await ctx.send("⚠️ Could not deobfuscate - unknown pattern")
        return
    
    if len(result) > 1900:
        with tempfile.NamedTemporaryFile(mode='w', suffix='.lua', delete=False) as f:
            f.write(result)
            await ctx.send(file=discord.File(f.name, filename='deobfuscated.lua'))
        os.unlink(f.name)
    else:
        await ctx.send(f"```lua\n{result}\n```")
    
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
    print(f"📡 Commands: .get <id/url>, .deobf, .detect")

bot.run(TOKEN)
