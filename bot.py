import discord
from discord.ext import commands
import aiohttp
import tempfile
import os
import re
import sys
import base64

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

def deobfuscate_wearedevs(content):
    """Deobfuscate WeAreDevs obfuscator (v1.0.0)"""
    
    print("Detected WeAreDevs obfuscator")
    
    # Step 1: Extract the large string table 'd'
    # Pattern: local d = {"\\076\\082\\089...", ...}
    table_pattern = r'local d = \{([^}]+)\}'
    table_match = re.search(table_pattern, content)
    
    if not table_match:
        return content
    
    table_content = table_match.group(1)
    
    # Step 2: Parse all quoted strings in the table
    strings = re.findall(r'"((?:[^"\\]|\\.)*)"', table_content)
    
    # Step 3: Decode each string from octal/escape sequences
    decoded_strings = []
    for s in strings:
        # Replace \XXX octal sequences
        decoded = re.sub(r'\\(\d{3})', lambda m: chr(int(m.group(1), 8)), s)
        # Replace \" with "
        decoded = decoded.replace('\\"', '"')
        # Replace \\ with \
        decoded = decoded.replace('\\\\', '\\')
        decoded_strings.append(decoded)
    
    # Step 4: Replace references to d[index] with actual strings
    result = content
    for i, decoded in enumerate(decoded_strings, 1):
        # Replace d[number] with the decoded string
        result = re.sub(r'd\[%d\]' % i, repr(decoded), result)
        result = re.sub(r'd\[%d\]' % i, repr(decoded), result)
    
    # Step 5: Remove the table definition line
    result = re.sub(r'local d = \{.*?\};?', '', result, flags=re.DOTALL)
    
    # Step 6: Extract and decode the return statement
    # Look for the big encoded block at the end
    encoded_pattern = r'return\(function\(([^)]+)\)return\(g\((\d+)[^)]*\)\)\(Y\(l\)\)end\)\([^)]*\)\.\.\.\)'
    
    # Step 7: Clean up
    result = re.sub(r'\n\s*\n', '\n', result)
    
    return result

def deobfuscate_general(content):
    """General deobfuscation for simple patterns"""
    
    # Decode string.char patterns
    def decode_string_chars(match):
        chars = match.group(1)
        numbers = re.findall(r'(\d+)', chars)
        try:
            decoded = ''.join(chr(int(n)) for n in numbers)
            return f'"{decoded}"'
        except:
            return match.group(0)
    
    content = re.sub(r'string\.char\(([^)]+)\)', decode_string_chars, content)
    
    # Decode \xxx octal patterns
    content = re.sub(r'\\(\d{3})', lambda m: chr(int(m.group(1), 8)), content)
    
    # Remove comments
    content = re.sub(r'--\[\[.*?\]\]', '', content, flags=re.DOTALL)
    
    return content

def detect_obfuscator(content):
    content_lower = content.lower()
    
    if 'wearedevs' in content_lower or 'wearedevs.net/obfuscator' in content:
        return 'wearedevs'
    if 'moonsec' in content_lower:
        return 'moonsec'
    if 'ironbrew' in content_lower or 'ib2' in content_lower:
        return 'ironbrew'
    if 'prometheus' in content_lower:
        return 'prometheus'
    if 'luraph' in content_lower:
        return 'luraph'
    return 'unknown'

async def resolve_loadstrings(content, depth=0):
    if depth > 3:
        return content
    
    patterns = [
        r'loadstring\(game:HttpGet\(["\']([^"\']+)["\']\)\)\s*\(?\)?',
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
                                f'\n--[[ Resolved from {url} --]]\n{fetched}\n--[[ End resolve --]]\n'
                            )
                            content = await resolve_loadstrings(content, depth + 1)
                except:
                    pass
    return content

async def full_deobfuscate(content):
    original_size = len(content)
    obf_type = detect_obfuscator(content)
    
    print(f"Deobfuscating {obf_type}...")
    
    if obf_type == 'wearedevs':
        content = deobfuscate_wearedevs(content)
    else:
        # General decoding for other types
        content = deobfuscate_general(content)
    
    # Always try to resolve loadstrings
    content = await resolve_loadstrings(content)
    
    # Final cleanup
    content = re.sub(r'\n\s*\n', '\n', content)
    
    print(f"Result: {original_size} -> {len(content)} bytes")
    
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
    obf_type = detect_obfuscator(content)
    await ctx.send(f"✅ Got {len(content)} bytes\n```lua\n{preview}\n```")
    await ctx.send(f"🔧 Detected: **{obf_type}**\nUse `.deobf` to deobfuscate")

@bot.command(name='deobf')
async def deobfuscate(ctx):
    if ctx.author.id not in user_scripts:
        await ctx.send("❌ No script. Use `.get` first")
        return
    
    await ctx.send("🔧 Deobfuscating... (this may take a moment)")
    
    original = user_scripts[ctx.author.id]
    result = await full_deobfuscate(original)
    
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
    if ctx.author.id not in user_scripts:
        await ctx.send("❌ No script. Use `.get` first")
        return
    
    content = user_scripts[ctx.author.id]
    obf_type = detect_obfuscator(content)
    await ctx.send(f"🔍 **Detected obfuscator:** {obf_type}")

@bot.event
async def on_ready():
    print(f"✅ Lunr Bot ready - {bot.user}")
    print(f"📡 Invite: https://discord.com/oauth2/authorize?client_id={bot.user.id}&permissions=274877958144&scope=bot")

if __name__ == "__main__":
    bot.run(TOKEN)
