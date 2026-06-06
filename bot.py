import discord
from discord.ext import commands
import aiohttp
import tempfile
import os
import re
import sys
import base64
import zlib
import json

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


# ============ MOONSEC DEOBFUSCATOR ============

def moonsec_extract_strings(content):
    """Extract MoonSec string table"""
    # MoonSec pattern: local I = {"string1","string2",...}
    patterns = [
        r'local\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*\{((?:[^}]|\n)*?)\}',
        r'local\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*\{((?:[^{}]|\{[^{}]*\})*)\}'
    ]
    
    all_strings = {}
    
    for pattern in patterns:
        for match in re.finditer(pattern, content, re.DOTALL):
            var_name = match.group(1)
            table_content = match.group(2)
            
            # Extract quoted strings
            strings = re.findall(r'"([^"\\]*(?:\\.[^"\\]*)*)"', table_content)
            if strings:
                all_strings[var_name] = strings
                print(f"Found string table {var_name} with {len(strings)} entries")
    
    return all_strings


def moonsec_replace_string_refs(content, string_tables):
    """Replace table[i] references with actual strings"""
    result = content
    
    for var_name, strings in string_tables.items():
        for i, s in enumerate(strings, 1):
            # Replace var_name[i] and var_name [i]
            result = re.sub(rf'{var_name}\[({i})\]', f'"{s}"', result)
            result = re.sub(rf'{var_name}\s*\[\s*{i}\s*\]', f'"{s}"', result)
    
    return result


def moonsec_decode_xor_strings(content):
    """Decode MoonSec XOR encrypted strings"""
    # Pattern: (function(a,b)return a~b end)(string.char(0xXX), string.char(0xYY))
    xor_pattern = r'\(function\(([^,]+),([^)]+)\)return \1~\2 end\)\(([^,)]+),([^)]+)\)'
    
    def decode_xor(match):
        try:
            # Extract the two values
            val1 = match.group(3).strip()
            val2 = match.group(4).strip()
            
            # If they're string.char calls, extract the byte
            char1_match = re.search(r'string\.char\(0x([0-9A-Fa-f]+)\)', val1)
            char2_match = re.search(r'string\.char\(0x([0-9A-Fa-f]+)\)', val2)
            
            if char1_match and char2_match:
                byte1 = int(char1_match.group(1), 16)
                byte2 = int(char2_match.group(1), 16)
                result_char = chr(byte1 ^ byte2)
                return f'"{result_char}"'
        except:
            pass
        return match.group(0)
    
    return re.sub(xor_pattern, decode_xor, content)


def moonsec_decode_hex_strings(content):
    """Decode hex encoded strings: \x48\x65\x6c\x6c\x6f"""
    hex_pattern = r'\\x([0-9A-Fa-f]{2})'
    
    def decode_hex(match):
        return chr(int(match.group(1), 16))
    
    return re.sub(hex_pattern, decode_hex, content)


def moonsec_extract_chunks(content):
    """Extract and combine split string chunks"""
    # Pattern: "chunk1""chunk2"
    chunk_pattern = r'"([^"]*)"\s*"([^"]*)"'
    
    for _ in range(5):
        content = re.sub(chunk_pattern, r'"\1\2"', content)
    
    return content


def moonsec_remove_vm_boilerplate(content):
    """Remove MoonSec VM wrapper code"""
    # Remove the large VM function
    vm_patterns = [
        r'local\s+function\s+[a-z_]+\(\)[\s\S]*?end\s*--\[\[.*?\]\]',
        r'local\s+[a-z_]+\s*=\s*function\([^)]*\)[\s\S]*?end\s*\)[;]?',
        r'while[^do]*do[\s\S]*?end[;\s]*--\[\[.*?\]\]',
    ]
    
    for pattern in vm_patterns:
        content = re.sub(pattern, '', content, flags=re.DOTALL)
    
    return content


def moonsec_cleanup(content):
    """Final cleanup of deobfuscated code"""
    # Remove empty lines
    content = re.sub(r'\n\s*\n', '\n', content)
    
    # Remove trailing whitespace
    content = '\n'.join(line.rstrip() for line in content.splitlines())
    
    # Fix common patterns
    content = re.sub(r'local\s+([a-z_])\s*=\s*\1', r'local \1', content)
    
    return content


def moonsec_deobfuscate(content):
    """Main MoonSec deobfuscation pipeline"""
    print("Starting MoonSec deobfuscation...")
    original_len = len(content)
    
    # Stage 1: Decode hex strings
    content = moonsec_decode_hex_strings(content)
    print(f"  After hex decode: {len(content)} bytes")
    
    # Stage 2: Extract and decode XOR strings
    content = moonsec_decode_xor_strings(content)
    print(f"  After XOR decode: {len(content)} bytes")
    
    # Stage 3: Extract string tables
    string_tables = moonsec_extract_strings(content)
    if string_tables:
        content = moonsec_replace_string_refs(content, string_tables)
        print(f"  After string table replacement: {len(content)} bytes")
    
    # Stage 4: Combine split strings
    content = moonsec_extract_chunks(content)
    print(f"  After chunk combining: {len(content)} bytes")
    
    # Stage 5: Remove VM boilerplate
    content = moonsec_remove_vm_boilerplate(content)
    print(f"  After VM removal: {len(content)} bytes")
    
    # Stage 6: Final cleanup
    content = moonsec_cleanup(content)
    print(f"  Final: {len(content)} bytes (was {original_len})")
    
    return content


# ============ IRONBREW DEOBFUSCATOR ============

def ironbrew_deobfuscate(content):
    """IronBrew deobfuscation"""
    print("Starting IronBrew deobfuscation...")
    
    # IronBrew uses similar patterns
    content = moonsec_decode_hex_strings(content)
    
    string_tables = moonsec_extract_strings(content)
    if string_tables:
        content = moonsec_replace_string_refs(content, string_tables)
    
    # Remove IronBrew environment checks
    content = re.sub(r'if\s+syn\s+then[\s\S]*?end', '', content, flags=re.DOTALL)
    content = re.sub(r'if\s+identifyexecutor\s*\(\)[\s\S]*?end', '', content, flags=re.DOTALL)
    
    content = moonsec_cleanup(content)
    
    return content


# ============ GENERAL DEOBFUSCATION ============

def decode_general(content):
    """General deobfuscation for simple patterns"""
    # Decode string.char
    content = re.sub(r'string\.char\(([^)]+)\)', 
                     lambda m: f'"{chr(int(m.group(1).split(",")[0].strip()))}"', 
                     content)
    
    # Decode octal
    content = re.sub(r'\\(\d{3})', lambda m: chr(int(m.group(1), 8)), content)
    
    return content


def detect_obfuscator(content):
    content_lower = content.lower()
    
    # MoonSec detection
    if re.search(r'moonsec|moon[\s_-]?sec', content_lower):
        return 'moonsec'
    
    # IronBrew detection
    if re.search(r'ironbrew|ib2', content_lower):
        return 'ironbrew'
    
    # Check for MoonSec VM patterns
    if re.search(r'local\s+[A-Za-z_]\s*=\s*\{\s*["\']', content):
        if re.search(r'string\.char\(0x[0-9A-Fa-f]{2}\)', content):
            return 'moonsec'
    
    # WeAreDevs detection
    if 'wearedevs.net/obfuscator' in content:
        return 'wearedevs'
    
    # Prometheus detection
    if 'prometheus' in content_lower:
        return 'prometheus'
    
    return 'unknown'


async def resolve_loadstrings(content, depth=0):
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
                                f'\n--[[ Resolved from {url} --]]\n{fetched}\n--[[ End resolve --]]\n'
                            )
                            content = await resolve_loadstrings(content, depth + 1)
                except:
                    pass
    return content


async def full_deobfuscate(content):
    original_size = len(content)
    obf_type = detect_obfuscator(content)
    
    print(f"Detected: {obf_type}")
    
    if obf_type == 'moonsec':
        content = moonsec_deobfuscate(content)
    elif obf_type == 'ironbrew':
        content = ironbrew_deobfuscate(content)
    else:
        content = decode_general(content)
    
    # Always resolve loadstrings
    content = await resolve_loadstrings(content)
    
    print(f"Deobfuscation complete: {original_size} -> {len(content)} bytes")
    
    return content, obf_type


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
    result, obf_type = await full_deobfuscate(original)
    
    # Check if any changes were made
    if result == original:
        await ctx.send(f"⚠️ No deobfuscation changes detected for {obf_type}. The script may use advanced VM protection.")
    
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
    
    # Show details
    details = []
    if re.search(r'local\s+[A-Za-z_]+\s*=\s*\{\s*["\']', content):
        details.append("String table detected")
    if re.search(r'string\.char\(0x', content):
        details.append("Hex obfuscation detected")
    if re.search(r'\\x[0-9A-Fa-f]{2}', content):
        details.append("Escape sequence detected")
    
    await ctx.send(f"🔍 **Obfuscator:** {obf_type}\n" + "\n".join(details))


@bot.event
async def on_ready():
    print(f"✅ Lunr Bot ready - {bot.user}")
    print(f"📡 Invite: https://discord.com/oauth2/authorize?client_id={bot.user.id}&permissions=274877958144&scope=bot")


if __name__ == "__main__":
    bot.run(TOKEN)
