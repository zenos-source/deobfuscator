import discord
from discord.ext import commands
import aiohttp
import tempfile
import os
import subprocess
import asyncio

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
    return 'Unknown'

async def deobf_with_larry(content):
    """Use the Larry Dumper Lua script to deobfuscate"""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.lua', delete=False) as f:
        f.write(content)
        input_file = f.name
    
    output_file = tempfile.NamedTemporaryFile(mode='w', suffix='.lua', delete=False).name
    
    try:
        # Run the Larry dumper
        proc = await asyncio.create_subprocess_exec(
            'lua', 'larry.lua', input_file, output_file,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
        
        if proc.returncode == 0 and os.path.exists(output_file):
            with open(output_file, 'r') as f:
                result = f.read()
            return result
        else:
            return content
    except Exception as e:
        print(f"Larry error: {e}")
        return content
    finally:
        for f in [input_file, output_file]:
            if os.path.exists(f):
                os.unlink(f)

def basic_deobf(content):
    """Basic WeAreDevs deobfuscation"""
    result = content
    result = re.sub(r'\\(\d{3})', lambda m: chr(int(m.group(1), 8)), result)
    result = re.sub(r'\\x([0-9a-fA-F]{2})', lambda m: chr(int(m.group(1), 16)), result)
    result = re.sub(r'string\.char\(([^)]+)\)', lambda m: ''.join(chr(int(x.strip())) for x in m.group(1).split(',')), result)
    return result

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
    
    if obf_type == 'MoonSec':
        await ctx.send("🔧 Using Larry Dumper for MoonSec...")
        result = await deobf_with_larry(content)
    else:
        result = basic_deobf(content)
    
    if result == content or len(result) < 100:
        await ctx.send("⚠️ Could not deobfuscate fully. Try using the Larry Dumper manually.")
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
    print(f"📡 Commands: .get, .deobf, .detect")

bot.run(TOKEN)
