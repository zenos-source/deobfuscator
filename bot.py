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

# ============ IRONBREW SPECIFIC DECODING ============

def decode_ironbrew_string_table(content):
    """IronBrew string table extraction and replacement"""
    # Pattern for IronBrew string table
    # local a = {[1] = "string1", [2] = "string2", ...}
    string_table_pattern = r'local\s+([a-z_]+)\s*=\s*\{([^}]+)\}'
    
    for match in re.finditer(string_table_pattern, content):
        table_var = match.group(1)
        table_content = match.group(2)
        
        # Extract string mappings
        mappings = {}
        for item in re.finditer(r'\[(\d+)\]\s*=\s*["\']([^"\']+)["\']', table_content):
            idx = int(item.group(1))
            val = item.group(2)
            mappings[idx] = val
        
        # Replace accesses like a[1] with actual strings
        for idx, val in mappings.items():
            content = content.replace(f'{table_var}[{idx}]', f'"{val}"')
            content = content.replace(f'{table_var} [{idx}]', f'"{val}"')
    
    return content

def decode_ironbrew_concat_patterns(content):
    """Decode IronBrew's string concatenation patterns"""
    # Pattern: "a".."b".."c"
    concat_pattern = r'(["\'])([^\1]+?)\1\.\.(["\'])([^\3]+?)\3'
    
    for _ in range(5):  # Multiple passes for nested concats
        content = re.sub(concat_pattern, lambda m: f'"{m.group(2) + m.group(4)}"', content)
    
    return content

def decode_ironbrew_hex_obfuscation(content):
    """Decode IronBrew's hex obfuscation"""
    # Pattern: '\x48\x65\x6c\x6c\x6f'
    hex_pattern = r'\\x([0-9a-fA-F]{2})'
    
    def replace_hex(match):
        return chr(int(match.group(1), 16))
    
    content = re.sub(hex_pattern, replace_hex, content)
    return content

def decode_ironbrew_loadstring_chains(content):
    """Extract and execute IronBrew loadstring chains"""
    # Pattern: loadstring(string.char(0x...))()
    loadstring_pattern = r'loadstring\(([^)]+)\)\(\)'
    
    for match in re.finditer(loadstring_pattern, content):
        try:
            # Extract the inner code
            inner = match.group(1)
            # Look for string.char sequences
            char_pattern = r'string\.char\(([^)]+)\)'
            char_match = re.search(char_pattern, inner)
            if char_match:
                chars = char_match.group(1).split(',')
                decoded = ''.join(chr(int(c.strip(), 16)) for c in chars)
                content = content.replace(match.group(0), f'--[[ loadstring decoded ]]\n{decoded}')
        except:
            pass
    
    return content

# ============ MOONSEC SPECIFIC DECODING ============

def decode_moonsec_string_table(content):
    """MoonSec string table extraction (similar to IronBrew)"""
    # MoonSec often uses: local I = {..., "string1", "string2", ...}
    table_pattern = r'local\s+([A-Z_])\s*=\s*\{([^}]+)\}'
    
    for match in re.finditer(table_pattern, content):
        table_var = match.group(1)
        table_content = match.group(2)
        
        # Extract strings by index (MoonSec uses array-style)
        strings = re.findall(r'["\']([^"\']+)["\']', table_content)
        
        for idx, val in enumerate(strings, 1):
            content = content.replace(f'{table_var}[{idx}]', f'"{val}"')
    
    return content

def decode_moonsec_unicode(content):
    """Decode MoonSec's unicode escape sequences"""
    # Pattern: \uXXXX
    unicode_pattern = r'\\u([0-9a-fA-F]{4})'
    
    def replace_unicode(match):
        return chr(int(match.group(1), 16))
    
    content = re.sub(unicode_pattern, replace_unicode, content)
    return content

def decode_moonsec_bytecode(content):
    """Extract MoonSec bytecode and attempt decompilation"""
    # Pattern for bytecode arrays
    bytecode_pattern = r'string\.char\(([^)]+)\)'
    
    for match in re.finditer(bytecode_pattern, content):
        try:
            chars = match.group(1).split(',')
            decoded = ''.join(chr(int(c.strip())) for c in chars if c.strip().isdigit())
            content = content.replace(match.group(0), f'"{decoded}"')
        except:
            pass
    
    return content

# ============ COMMON DECODING FUNCTIONS ============

def decode_base64(content):
    b64_pattern = r'["\']([A-Za-z0-9+/]{20,}={0,2})["\']'
    result = content
    for match in re.finditer(b64_pattern, content):
        b64_str = match.group(1)
        try:
            decoded = base64.b64decode(b64_str).decode('utf-8', errors='ignore')
            result = result.replace(f'"{b64_str}"', f'"{decoded}"')
        except:
            pass
    return result

def decode_hex(content):
    result = content
    hex_pattern = r'["\']([0-9a-fA-F]{20,})["\']'
    for match in re.finditer(hex_pattern, content):
        hex_str = match.group(1)
        try:
            decoded = bytes.fromhex(hex_str).decode('utf-8', errors='ignore')
            result = result.replace(f'"{hex_str}"', f'"{decoded}"')
        except:
            pass
    
    # Also handle \xXX format
    hex_escape_pattern = r'\\x([0-9a-fA-F]{2})'
    result = re.sub(hex_escape_pattern, lambda m: chr(int(m.group(1), 16)), result)
    return result

def decode_gzip(content):
    """Decompress gzip-encoded strings"""
    gzip_pattern = r'loadstring\(decompress\(["\']([^"\']+)["\']\)\)'
    for match in re.finditer(gzip_pattern, content):
        try:
            import gzip
            compressed = base64.b64decode(match.group(1))
            decompressed = gzip.decompress(compressed).decode('utf-8', errors='ignore')
            content = content.replace(match.group(0), decompressed)
        except:
            pass
    return content

def decode_concatenations(content):
    """Decode nested string concatenations"""
    concat_pattern = r'(["\'][^\'"]+["\'])\.\.(["\'])([^\'"]+)\2'
    for _ in range(10):
        content = re.sub(concat_pattern, lambda m: f'"{m.group(1).strip("\"\'") + m.group(3)}"', content)
    return content

def remove_environment_checks(content):
    """Remove IronBrew/MoonSec environment detection code"""
    patterns_to_remove = [
        r'if .*?syn\.request.*?then[\s\S]*?end',
        r'if .*?identifyexecutor.*?then[\s\S]*?end',
        r'if .*?getgenv.*?then[\s\S]*?end',
        r'pcall\(function\(\)[\s\S]*?end\)',
    ]
    
    for pattern in patterns_to_remove:
        content = re.sub(pattern, '', content, flags=re.IGNORECASE)
    
    return content

def cleanup_whitespace(content):
    """Clean up excessive whitespace and line breaks"""
    content = re.sub(r'\n\s*\n', '\n', content)
    content = re.sub(r';\s*\n', '\n', content)
    content = re.sub(r'\{\s*\n\s*\}', '{}', content)
    return content

def detect_obfuscator(content):
    content_lower = content.lower()
    
    if 'moonsec' in content_lower or 'moonsec' in content_lower:
        return 'moonsec'
    if 'ironbrew' in content_lower or 'ib2' in content_lower:
        return 'ironbrew'
    if 'prometheus' in content_lower:
        return 'prometheus'
    if 'luraph' in content_lower:
        return 'luraph'
    if 'luarmor' in content_lower:
        return 'luarmor'
    # Check for characteristic patterns
    if re.search(r'local\s+[A-Z_]+\s*=\s*\{[\d,]+}', content):
        return 'ironbrew'
    if re.search(r'local\s+[a-z]+\s*=\s*\{[^}]*["\'][^"\']*["\']', content):
        return 'moonsec'
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
                                fetched
                            )
                            content = await resolve_loadstrings(content, depth + 1)
                except:
                    pass
    return content

async def full_deobfuscate(content):
    original_size = len(content)
    changes_made = False
    
    # Stage 1: Basic decoding
    new_content = decode_hex(content)
    if new_content != content:
        changes_made = True
        content = new_content
    
    new_content = decode_base64(content)
    if new_content != content:
        changes_made = True
        content = new_content
    
    # Stage 2: Obfuscator-specific decoding
    obf_type = detect_obfuscator(content)
    
    if obf_type == 'ironbrew':
        print("Applying IronBrew deobfuscation...")
        new_content = decode_ironbrew_string_table(content)
        if new_content != content:
            changes_made = True
            content = new_content
        
        new_content = decode_ironbrew_concat_patterns(content)
        if new_content != content:
            changes_made = True
            content = new_content
        
        new_content = decode_ironbrew_hex_obfuscation(content)
        if new_content != content:
            changes_made = True
            content = new_content
        
        new_content = decode_ironbrew_loadstring_chains(content)
        if new_content != content:
            changes_made = True
            content = new_content
    
    elif obf_type == 'moonsec':
        print("Applying MoonSec deobfuscation...")
        new_content = decode_moonsec_string_table(content)
        if new_content != content:
            changes_made = True
            content = new_content
        
        new_content = decode_moonsec_unicode(content)
        if new_content != content:
            changes_made = True
            content = new_content
        
        new_content = decode_moonsec_bytecode(content)
        if new_content != content:
            changes_made = True
            content = new_content
    
    # Stage 3: General decoding
    new_content = decode_concatenations(content)
    if new_content != content:
        changes_made = True
        content = new_content
    
    new_content = decode_gzip(content)
    if new_content != content:
        changes_made = True
        content = new_content
    
    # Stage 4: Cleanup
    new_content = remove_environment_checks(content)
    if new_content != content:
        changes_made = True
        content = new_content
    
    new_content = cleanup_whitespace(content)
    if new_content != content:
        changes_made = True
        content = new_content
    
    # Stage 5: Follow loadstrings
    new_content = await resolve_loadstrings(content)
    if new_content != content:
        changes_made = True
        content = new_content
    
    print(f"Deobfuscated: {original_size} -> {len(content)} bytes ({obf_type}, changes={changes_made})")
    
    if not changes_made:
        return content, False
    
    return content, True

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
    result, changed = await full_deobfuscate(original)
    
    if not changed:
        await ctx.send("⚠️ No changes detected. The script may use advanced VM obfuscation (Luraph/Luarmor) that requires external tools.")
    
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
    
    # Show more details
    details = []
    if re.search(r'local\s+[A-Z_]+\s*=\s*\{[\d,]+}', content):
        details.append("IronBrew string table detected")
    if re.search(r'loadstring\(game:HttpGet', content):
        details.append("External script loading detected")
    if re.search(r'string\.char\(0x', content):
        details.append("Hex obfuscation detected")
    
    await ctx.send(f"🔍 **Detected obfuscator:** {obf_type}\n" + "\n".join(details))

@bot.event
async def on_ready():
    print(f"✅ Lunr Bot ready - {bot.user}")
    print(f"📡 Invite: https://discord.com/oauth2/authorize?client_id={bot.user.id}&permissions=274877958144&scope=bot")

if __name__ == "__main__":
    bot.run(TOKEN)
