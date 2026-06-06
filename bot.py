import discord
from discord.ext import commands
import aiohttp
import tempfile
import os
import re
import sys
import base64
import zlib

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
    """Decode hex strings like '1b1c2f1f'"""
    result = content
    hex_pattern = r'["\']([0-9a-fA-F]{20,})["\']'
    for match in re.finditer(hex_pattern, content):
        hex_str = match.group(1)
        try:
            decoded = bytes.fromhex(hex_str).decode('utf-8', errors='ignore')
            result = result.replace(f'"{hex_str}"', f'"{decoded}"')
        except:
            pass
    return result

def decode_base64(content):
    """Decode base64 strings"""
    b64_pattern = r'["\']([A-Za-z0-9+/]{20,}={0,2})["\']'
    for match in re.finditer(b64_pattern, content):
        b64_str = match.group(1)
        try:
            decoded = base64.b64decode(b64_str).decode('utf-8', errors='ignore')
            result = content.replace(f'"{b64_str}"', f'"{decoded}"')
        except:
            pass
    return content

def decode_xor(content):
    """Handle XOR obfuscation patterns"""
    # Pattern: string.char(0x1b)..string.char(0x1c)..
    xor_pattern = r'string\.char\(0x([0-9a-fA-F]{2})\)'
    matches = re.findall(xor_pattern, content)
    if matches:
        decoded = ''.join(chr(int(c, 16)) for c in matches)
        return f'--[[ XOR decoded: {decoded[:200]} ]]\n{content}'
    return content

def deobf_moonsec(content):
    """MoonSec-specific deobfuscation"""
    # Remove MoonSec loader wrapper
    content = re.sub(r'local [a-z_]+ = .*?loadstring\(.*?\)\(\)', '', content, flags=re.DOTALL)
    # Clean up variable names
    content = re.sub(r'local [a-z_] = (function|table|string|math)', r'local \1', content)
    return content

def deobf_ironbrew(content):
    """IronBrew-specific deobfuscation"""
    # Remove IronBrew environment checks
    content = re.sub(r'if .*?syn.*?then.*?end', '', content, flags=re.DOTALL)
    content = re.sub(r'if .*?identifyexecutor.*?then.*?end', '', content, flags=re.DOTALL)
    return content

def deobf_prometheus(content):
    """Prometheus-specific cleanup"""
    # Remove Prometheus loader
    content = re.sub(r'loadstring\(.*?prometheus.*?\)\(\)', '', content, flags=re.IGNORECASE)
    return content

def beautify_code(content):
    """Basic code beautification"""
    # Remove excessive newlines
    content = re.sub(r'\n\s*\n', '\n', content)
    # Fix spacing
    content = re.sub(r'(\S)=(\S)', r'\1 = \2', content)
    return content

async def resolve_loadstrings(content, depth=0):
    """Follow loadstring chains"""
    if depth > 3:
        return content
    
    patterns = [
        r'loadstring\(game:HttpGet\(["\']([^"\']+)["\']\)\)\s*\(?\)?',
        r'loadstring\(syn\.request\(.*?url=["\']([^"\']+)["\']',
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
                                fetched
                            )
                            content = await resolve_loadstrings(content, depth + 1)
                except:
                    pass
    return content

def detect_obfuscator(content):
    """Detect which obfuscator was used"""
    content_lower = content.lower()
    
    if 'moonsec' in content_lower:
        return 'moonsec'
    if 'ironbrew' in content_lower or 'ib2' in content_lower:
        return 'ironbrew'
    if 'prometheus' in content_lower:
        return 'prometheus'
    if 'luraph' in content_lower:
        return 'luraph'
    if 'luarmor' in content_lower:
        return 'luarmor'
    return 'unknown'

async def full_deobfuscate(content):
    """Complete deobfuscation pipeline"""
    original_size = len(content)
    
    # Stage 1: Basic decoding
    content = decode_hex(content)
    content = decode_base64(content)
    content = decode_xor(content)
    
    # Stage 2: Follow loadstrings
    content = await resolve_loadstrings(content)
    
    # Stage 3: Detect and apply specific deobfuscation
    obf_type = detect_obfuscator(content)
    
    if obf_type == 'moonsec':
        content = deobf_moonsec(content)
    elif obf_type == 'ironbrew':
        content = deobf_ironbrew(content)
    elif obf_type == 'prometheus':
        content = deobf_prometheus(content)
    
    # Stage 4: Clean up
    content = beautify_code(content)
    
    print(f"Deobfuscated: {original_size} -> {len(content)} bytes ({obf_type})")
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
    
    user_scripts[ctx.author.id] = content
    
    preview = content[:400] + ('...' if len(content) > 400 else '')
    await ctx.send(f"✅ Got {len(content)} bytes\n```lua\n{preview}\n```")
    await ctx.send(f"🔧 Detected: {detect_obfuscator(content)}\nUse `.deobf` to deobfuscate")

@bot.command(name='deobf')
async def deobfuscate(ctx):
    if ctx.author.id not in user_scripts:
        await ctx.send("❌ No script. Use `.get` first")
        return
    
    await ctx.send("🔧 Deobfuscating... (this may take a moment)")
    
    original = user_scripts[ctx.author.id]
    result = await full_deobfuscate(original)
    
    # Check if deobfuscation actually changed anything
    if result == original:
        await ctx.send("⚠️ No changes detected. The script may use advanced obfuscation that requires external tools (LuraphDeobfuscator, De4Lua).")
    
    if len(result) > 1900:
        with tempfile.NamedTemporaryFile(mode='w', suffix='.lua', delete=False) as f:
            f.write(result)
            await ctx.send(file=discord.File(f.name, filename='deobfuscated.lua'))
        os.unlink(f.name)
    else:
        await ctx.send(f"```lua\n{result}\n```")
    
    del user_scripts[ctx.author.id]

@bot.event
async def on_ready():
    print(f"✅ Lunr Bot ready - {bot.user}")
    print(f"📡 Invite: https://discord.com/oauth2/authorize?client_id={bot.user.id}&permissions=274877958144&scope=bot")

if __name__ == "__main__":
    bot.run(TOKEN)
