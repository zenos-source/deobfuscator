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

# ============================================================
# FETCH FUNCTIONS
# ============================================================

async def fetch_url(url):
    async with aiohttp.ClientSession() as session:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        try:
            async with session.get(url, headers=headers, timeout=15) as resp:
                if resp.status == 200:
                    return await resp.text()
        except:
            pass
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
    # Direct URL
    if target.startswith('http'):
        return await fetch_url(target)
    
    # Roblox asset ID
    if target.isdigit():
        url = f"https://raw.roblox.com/asset/?id={target}"
        return await fetch_url(url)
    
    # Loadstring code
    if 'loadstring' in target:
        url = extract_url_from_loadstring(target)
        if url:
            return await fetch_url(url)
    
    # Any URL in text
    url_match = re.search(r'https?://[^\s"\'<>]+', target)
    if url_match:
        return await fetch_url(url_match.group(0))
    
    return None

# ============================================================
# DEOBFUSCATION FUNCTIONS
# ============================================================

def decode_octal_strings(content):
    """Decode \123 octal patterns"""
    return re.sub(r'\\(\d{3})', lambda m: chr(int(m.group(1), 8)), content)

def decode_hex_strings(content):
    """Decode \x48 hex patterns"""
    return re.sub(r'\\x([0-9a-fA-F]{2})', lambda m: chr(int(m.group(1), 16)), content)

def decode_string_char(content):
    """Decode string.char(65,66,67) patterns"""
    pattern = r'string\.char\(([^)]+)\)'
    def replace(match):
        numbers = re.findall(r'(\d+)', match.group(1))
        try:
            return '"' + ''.join(chr(int(n)) for n in numbers) + '"'
        except:
            return match.group(0)
    return re.sub(pattern, replace, content)

def wearedevs_deobfuscate(content):
    """Complete WeAreDevs deobfuscator"""
    print("Running WeAreDevs deobfuscator...")
    
    # Step 1: Find the string table
    table_match = re.search(r'local d = \{(.*?)\};', content, re.DOTALL)
    if not table_match:
        return content
    
    table_content = table_match.group(1)
    
    # Step 2: Extract and decode strings
    raw_strings = re.findall(r'"((?:\\\d{3}|[^"])*)"', table_content)
    decoded_strings = []
    
    for s in raw_strings:
        decoded = re.sub(r'\\(\d{3})', lambda m: chr(int(m.group(1), 8)), s)
        decoded = decoded.replace('\\\\', '\\')
        decoded_strings.append(decoded)
    
    print(f"  Decoded {len(decoded_strings)} strings")
    
    # Step 3: Replace references
    result = content
    for i, decoded in enumerate(decoded_strings, 1):
        result = re.sub(r'd\s*\[\s*' + str(i) + r'\s*\]', repr(decoded), result)
    
    # Step 4: Remove the table
    result = re.sub(r'local d = \{.*?\};', '', result, flags=re.DOTALL)
    
    # Step 5: Extract inner function
    func_match = re.search(r'return\(function\([^)]*\)(.*?)end\)', result, re.DOTALL)
    if func_match:
        inner = func_match.group(1)
        inner = re.sub(r'^[^{]*\{', '', inner)
        inner = re.sub(r'\}[^}]*$', '', inner)
        result = inner
    
    return result

def moonsec_string_extract(content):
    """Extract MoonSec string tables"""
    result = content
    
    # Find local TABLE = { "string1", "string2", ... }
    table_pattern = r'local\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*\{([^}]+)\}'
    
    for match in re.finditer(table_pattern, content):
        var_name = match.group(1)
        table_body = match.group(2)
        
        # Extract strings
        strings = re.findall(r'"((?:[^"\\]|\\.)*)"', table_body)
        
        for i, s in enumerate(strings, 1):
            result = re.sub(rf'{var_name}\[(\s*){i}(\s*)\]', f'"{s}"', result)
    
    return result

def moonsec_deobfuscate(content):
    """MoonSec deobfuscation pipeline"""
    print("Running MoonSec deobfuscator...")
    
    # Decode hex
    content = decode_hex_strings(content)
    
    # Decode string.char
    content = decode_string_char(content)
    
    # Extract string tables
    content = moonsec_string_extract(content)
    
    # Clean up
    content = re.sub(r'\n\s*\n', '\n', content)
    
    return content

async def resolve_loadstrings(content, depth=0):
    """Follow loadstring chains"""
    if depth > 3:
        return content
    
    pattern = r'loadstring\(game:HttpGet\(["\']([^"\']+)["\']\)\)\s*\(?\)?'
    matches = re.findall(pattern, content)
    
    async with aiohttp.ClientSession() as session:
        for url in matches:
            try:
                async with session.get(url, timeout=10) as resp:
                    if resp.status == 200:
                        fetched = await resp.text()
                        content = content.replace(
                            f'loadstring(game:HttpGet("{url}"))',
                            f'\n--[[ Resolved from {url} ]]\n{fetched}\n--[[ End resolve ]]\n'
                        )
                        content = await resolve_loadstrings(content, depth + 1)
            except:
                pass
    
    return content

def detect_obfuscator(content):
    """Detect which obfuscator was used"""
    if 'wearedevs.net/obfuscator' in content:
        return 'wearedevs'
    if re.search(r'local d = \{\\d{3}', content):
        return 'wearedevs'
    if 'moonsec' in content.lower():
        return 'moonsec'
    if 'ironbrew' in content.lower():
        return 'ironbrew'
    if 'prometheus' in content.lower():
        return 'prometheus'
    if 'luraph' in content.lower():
        return 'luraph'
    return 'unknown'

async def full_deobfuscate(content):
    """Main deobfuscation pipeline"""
    original_len = len(content)
    obf_type = detect_obfuscator(content)
    
    print(f"Detected: {obf_type}")
    
    # Always run basic decoders
    content = decode_octal_strings(content)
    content = decode_hex_strings(content)
    content = decode_string_char(content)
    
    # Run specific deobfuscators
    if obf_type == 'wearedevs':
        content = wearedevs_deobfuscate(content)
    elif obf_type == 'moonsec':
        content = moonsec_deobfuscate(content)
    elif obf_type == 'ironbrew':
        content = moonsec_string_extract(content)
        content = decode_string_char(content)
    
    # Follow loadstrings
    content = await resolve_loadstrings(content)
    
    # Final cleanup
    content = re.sub(r'\n\s*\n', '\n', content)
    content = re.sub(r';\s*\n', '\n', content)
    
    print(f"Result: {original_len} -> {len(content)} bytes")
    
    return content, obf_type

# ============================================================
# DISCORD COMMANDS
# ============================================================

@bot.command(name='get')
async def get_script(ctx, *, target):
    """Fetch a script from URL, asset ID, or loadstring code"""
    await ctx.send(f"🔍 Fetching...")
    
    content = await fetch_script(target)
    
    if not content:
        await ctx.send("❌ Could not fetch script. Try:\n- Direct URL\n- Roblox asset ID (numbers only)\n- Loadstring code containing a URL")
        return
    
    user_scripts[ctx.author.id] = content
    
    obf_type = detect_obfuscator(content)
    preview = content[:400] + ('...' if len(content) > 400 else '')
    
    await ctx.send(f"✅ {len(content)} bytes | Detected: **{obf_type}**")
    await ctx.send(f"```lua\n{preview}\n```")
    await ctx.send("🔧 Use `.deobf` to deobfuscate")

@bot.command(name='deobf')
async def deobfuscate(ctx):
    """Deobfuscate the last fetched script"""
    if ctx.author.id not in user_scripts:
        await ctx.send("❌ No script. Use `.get` first")
        return
    
    await ctx.send("🔧 Deobfuscating... (this may take a moment)")
    
    original = user_scripts[ctx.author.id]
    result, obf_type = await full_deobfuscate(original)
    
    if result == original:
        await ctx.send(f"⚠️ Could not deobfuscate **{obf_type}**. The script may use advanced VM protection.")
        return
    
    if len(result) > 1900:
        with tempfile.NamedTemporaryFile(mode='w', suffix='.lua', delete=False) as f:
            f.write(result)
            await ctx.send(file=discord.File(f.name, filename='deobfuscated.lua'))
        os.unlink(f.name)
    else:
        await ctx.send(f"```lua\n{result}\n```")
    
    del user_scripts[ctx.author.id]

@bot.command(name='detect')
async def detect_only(ctx):
    """Detect obfuscator without deobfuscating"""
    if ctx.author.id not in user_scripts:
        await ctx.send("❌ No script. Use `.get` first")
        return
    
    content = user_scripts[ctx.author.id]
    obf_type = detect_obfuscator(content)
    await ctx.send(f"🔍 **Obfuscator:** {obf_type}")

@bot.command(name='help')
async def help_command(ctx):
    """Show available commands"""
    embed = discord.Embed(
        title="Lunr Bot Commands",
        description="Lua deobfuscation bot for Roblox scripts",
        color=0x5865F2
    )
    embed.add_field(name="`.get <url/id/loadstring>`", value="Fetch a script", inline=False)
    embed.add_field(name="`.deobf`", value="Deobfuscate the fetched script", inline=False)
    embed.add_field(name="`.detect`", value="Detect obfuscator type", inline=False)
    embed.add_field(name="`.help`", value="Show this help", inline=False)
    embed.set_footer(text="Supports: WeAreDevs, MoonSec, IronBrew")
    await ctx.send(embed=embed)

@bot.event
async def on_ready():
    print(f"✅ Lunr Bot ready - {bot.user}")
    print(f"📡 Prefix: .")
    print(f"📡 Commands: .get, .deobf, .detect, .help")

if __name__ == "__main__":
    bot.run(TOKEN)
