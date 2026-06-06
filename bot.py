import discord
from discord.ext import commands
import aiohttp
import tempfile
import os
import re
import sys
import asyncio

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

# ============================================================
# FETCH FUNCTIONS
# ============================================================

async def fetch_url(url):
    async with aiohttp.ClientSession() as session:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        try:
            async with session.get(url, headers=headers, timeout=10) as resp:
                if resp.status == 200:
                    return await resp.text()
        except Exception as e:
            print(f"Fetch error: {e}")
    return None

def extract_url_from_loadstring(content):
    patterns = [
        r'loadstring\(game:HttpGet\(["\']([^"\']+)["\']\)\)',
        r'loadstring\(game:HttpGetAsync\(["\']([^"\']+)["\']\)\)',
        r'HttpGet\(["\']([^"\']+)["\']\)',
    ]
    for pattern in patterns:
        match = re.search(pattern, content)
        if match:
            return match.group(1)
    return None

async def fetch_script(target):
    if target.startswith('http'):
        return await fetch_url(target)
    
    if target.isdigit():
        url = f"https://raw.roblox.com/asset/?id={target}"
        return await fetch_url(url)
    
    if 'loadstring' in target:
        url = extract_url_from_loadstring(target)
        if url:
            return await fetch_url(url)
    
    url_match = re.search(r'https?://[^\s"\'<>]+', target)
    if url_match:
        return await fetch_url(url_match.group(0))
    
    return None

# ============================================================
# SIMPLE DEOBFUSCATION (NON-BLOCKING)
# ============================================================

def simple_deobfuscate(content):
    """Fast deobfuscation that won't timeout"""
    result = content
    changes = False
    
    # Decode octal sequences \123
    def decode_octal(match):
        nonlocal changes
        changes = True
        return chr(int(match.group(1), 8))
    
    result = re.sub(r'\\(\d{3})', decode_octal, result)
    
    # Decode hex sequences \x48
    def decode_hex(match):
        nonlocal changes
        changes = True
        return chr(int(match.group(1), 16))
    
    result = re.sub(r'\\x([0-9a-fA-F]{2})', decode_hex, result)
    
    # Decode string.char(65,66,67)
    def decode_string_char(match):
        nonlocal changes
        numbers = re.findall(r'(\d+)', match.group(1))
        try:
            return '"' + ''.join(chr(int(n)) for n in numbers) + '"'
        except:
            return match.group(0)
    
    result = re.sub(r'string\.char\(([^)]+)\)', decode_string_char, result)
    
    return result, changes

def wearedevs_fast(content):
    """Fast WeAreDevs deobfuscation"""
    result = content
    
    # Extract string table
    table_match = re.search(r'local d = \{(.*?)\};', content, re.DOTALL)
    if not table_match:
        return content, False
    
    table_content = table_match.group(1)
    raw_strings = re.findall(r'"((?:\\\d{3}|[^"])*)"', table_content)
    
    if not raw_strings:
        return content, False
    
    decoded_strings = []
    for s in raw_strings:
        decoded = re.sub(r'\\(\d{3})', lambda m: chr(int(m.group(1), 8)), s)
        decoded = decoded.replace('\\\\', '\\')
        decoded_strings.append(decoded)
    
    # Replace references
    for i, decoded in enumerate(decoded_strings, 1):
        result = re.sub(r'd\s*\[\s*' + str(i) + r'\s*\]', repr(decoded), result)
    
    # Remove the table
    result = re.sub(r'local d = \{.*?\};', '', result, flags=re.DOTALL)
    
    # Extract inner function if present
    func_match = re.search(r'return\(function\([^)]*\)(.*?)end\)', result, re.DOTALL)
    if func_match:
        inner = func_match.group(1)
        inner = re.sub(r'^[^{]*\{', '', inner)
        inner = re.sub(r'\}[^}]*$', '', inner)
        result = inner
    
    return result, True

def detect_obfuscator(content):
    if 'wearedevs.net/obfuscator' in content:
        return 'wearedevs'
    if re.search(r'local d = \{\\d{3}', content):
        return 'wearedevs'
    if 'moonsec' in content.lower():
        return 'moonsec'
    if 'ironbrew' in content.lower():
        return 'ironbrew'
    return 'unknown'

async def full_deobfuscate(content):
    """Non-blocking deobfuscation with timeout"""
    original_len = len(content)
    obf_type = detect_obfuscator(content)
    
    print(f"Detected: {obf_type}")
    
    result = content
    
    # Always run basic decoders
    result, changed = simple_deobfuscate(result)
    
    # Run specific deobfuscators
    if obf_type == 'wearedevs':
        result, changed2 = wearedevs_fast(result)
        changed = changed or changed2
    
    # Clean up whitespace
    result = re.sub(r'\n\s*\n', '\n', result)
    result = re.sub(r';\s*\n', '\n', result)
    
    # Remove excessive whitespace at start/end
    result = result.strip()
    
    print(f"Result: {original_len} -> {len(result)} bytes, changed={changed}")
    
    return result, obf_type, changed

# ============================================================
# DISCORD COMMANDS
# ============================================================

@bot.command(name='get')
async def get_script(ctx, *, target):
    await ctx.send(f"🔍 Fetching...")
    
    content = await fetch_script(target)
    
    if not content:
        await ctx.send("❌ Could not fetch script. Try:\n- Direct URL\n- Roblox asset ID (numbers only)\n- Loadstring code containing a URL")
        return
    
    user_scripts[ctx.author.id] = content
    
    obf_type = detect_obfuscator(content)
    preview = content[:300] + ('...' if len(content) > 300 else '')
    
    await ctx.send(f"✅ {len(content)} bytes | Detected: **{obf_type}**")
    await ctx.send(f"```lua\n{preview}\n```")
    await ctx.send("🔧 Use `.deobf` to deobfuscate")

@bot.command(name='deobf')
async def deobfuscate(ctx):
    if ctx.author.id not in user_scripts:
        await ctx.send("❌ No script. Use `.get` first")
        return
    
    # Send initial message
    msg = await ctx.send("🔧 Deobfuscating... (0%)")
    
    try:
        # Run deobfuscation with timeout
        original = user_scripts[ctx.author.id]
        
        # Update progress
        await msg.edit(content="🔧 Deobfuscating... (25%)")
        
        # Run deobfuscation (with timeout)
        result, obf_type, changed = await asyncio.wait_for(
            full_deobfuscate(original),
            timeout=30.0
        )
        
        await msg.edit(content="🔧 Deobfuscating... (75%)")
        
        if not changed or result == original:
            await msg.edit(content=f"⚠️ Could not deobfuscate **{obf_type}**. The script may use advanced VM protection or is not obfuscated.")
            return
        
        await msg.edit(content="🔧 Deobfuscating... (100%) - Sending result")
        
        # Send result
        if len(result) > 1900:
            with tempfile.NamedTemporaryFile(mode='w', suffix='.lua', delete=False) as f:
                f.write(result)
                await ctx.send(file=discord.File(f.name, filename='deobfuscated.lua'))
            os.unlink(f.name)
        else:
            await ctx.send(f"```lua\n{result}\n```")
        
        await msg.delete()
        del user_scripts[ctx.author.id]
        
    except asyncio.TimeoutError:
        await msg.edit(content="❌ Deobfuscation timed out after 30 seconds. The script is too large or complex.")
    except Exception as e:
        await msg.edit(content=f"❌ Error: {str(e)[:100]}")
        print(f"Deobf error: {e}")

@bot.command(name='detect')
async def detect_only(ctx):
    if ctx.author.id not in user_scripts:
        await ctx.send("❌ No script. Use `.get` first")
        return
    
    content = user_scripts[ctx.author.id]
    obf_type = detect_obfuscator(content)
    
    # Show more details
    details = []
    if re.search(r'\\\d{3}', content):
        details.append("- Octal escape sequences found")
    if re.search(r'\\x[0-9a-fA-F]{2}', content):
        details.append("- Hex escape sequences found")
    if re.search(r'string\.char\(', content):
        details.append("- string.char() patterns found")
    if re.search(r'local d = \{', content):
        details.append("- WeAreDevs string table found")
    
    await ctx.send(f"🔍 **Obfuscator:** {obf_type}\n" + "\n".join(details))

@bot.event
async def on_ready():
    print(f"✅ Lunr Bot ready - {bot.user}")
    print(f"📡 Commands: .get, .deobf, .detect")

if __name__ == "__main__":
    bot.run(TOKEN)
