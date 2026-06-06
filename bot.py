import discord
from discord.ext import commands
import aiohttp
import tempfile
import os
import re
import sys
import asyncio
import subprocess

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
        headers = {"User-Agent": "Lunr-Bot/1.0"}
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
# MOONSEC DEOBFUSCATION (Using external tool)
# ============================================================

def detect_obfuscator(content):
    content_lower = content.lower()
    if 'moonsec' in content_lower or re.search(r'local\s+\w+\s*=\s*\{[^}]*["\']', content):
        return 'moonsec'
    if 'wearedevs.net/obfuscator' in content:
        return 'wearedevs'
    if 'ironbrew' in content_lower:
        return 'ironbrew'
    if 'prometheus' in content_lower:
        return 'prometheus'
    return 'unknown'

async def moonsec_deobfuscate(input_path, output_path):
    """
    Use MoonsecDeobfuscator to devirtualize MoonSec V3
    This produces bytecode, then decompile with unluac
    """
    moonsec_dir = "./MoonsecDeobfuscator"
    luac_path = output_path.replace('.lua', '.luac')
    
    # Step 1: Devirtualize to bytecode
    result = subprocess.run(
        ['dotnet', 'run', '--project', moonsec_dir, '-dev', '-i', input_path, '-o', luac_path],
        capture_output=True,
        text=True,
        timeout=30
    )
    
    if result.returncode != 0:
        return False, result.stderr
    
    # Step 2: Decompile bytecode to Lua
    result2 = subprocess.run(
        ['java', '-jar', 'unluac.jar', luac_path],
        capture_output=True,
        text=True,
        timeout=10
    )
    
    if result2.returncode != 0:
        return False, result2.stderr
    
    with open(output_path, 'w') as f:
        f.write(result2.stdout)
    
    return True, "Success"

def simple_wearedevs_deobfuscate(content):
    """WeAreDevs deobfuscation"""
    result = content
    
    # Decode octal sequences
    result = re.sub(r'\\(\d{3})', lambda m: chr(int(m.group(1), 8)), result)
    
    # Decode hex sequences
    result = re.sub(r'\\x([0-9a-fA-F]{2})', lambda m: chr(int(m.group(1), 16)), result)
    
    # Decode string.char
    result = re.sub(r'string\.char\(([^)]+)\)', 
                    lambda m: '"' + ''.join(chr(int(n.strip())) for n in m.group(1).split(',')) + '"', 
                    result)
    
    return result

async def full_deobfuscate(content):
    """Main deobfuscation pipeline"""
    original_len = len(content)
    obf_type = detect_obfuscator(content)
    
    print(f"Detected: {obf_type}")
    
    if obf_type == 'moonsec':
        # Use external MoonSec deobfuscator
        with tempfile.NamedTemporaryFile(mode='w', suffix='.lua', delete=False) as f:
            f.write(content)
            input_path = f.name
        
        output_path = tempfile.NamedTemporaryFile(mode='w', suffix='.lua', delete=False).name
        
        try:
            success, message = await asyncio.wait_for(
                moonsec_deobfuscate(input_path, output_path),
                timeout=45.0
            )
            
            if success:
                with open(output_path, 'r') as f:
                    result = f.read()
                return result, obf_type, True
            else:
                print(f"MoonSec deobfuscation failed: {message}")
                return content, obf_type, False
        finally:
            for path in [input_path, output_path, output_path.replace('.lua', '.luac')]:
                if os.path.exists(path):
                    os.unlink(path)
    
    elif obf_type == 'wearedevs':
        result = simple_wearedevs_deobfuscate(content)
        return result, obf_type, result != content
    
    else:
        # Unknown obfuscator, try basic decoding
        result = simple_wearedevs_deobfuscate(content)
        return result, obf_type, result != content

# ============================================================
# DISCORD COMMANDS
# ============================================================

@bot.command(name='get')
async def get_script(ctx, *, target):
    await ctx.send(f"🔍 Fetching...")
    
    content = await fetch_script(target)
    
    if not content:
        await ctx.send("❌ Could not fetch script")
        return
    
    user_scripts[ctx.author.id] = content
    
    obf_type = detect_obfuscator(content)
    preview = content[:400] + ('...' if len(content) > 400 else '')
    
    await ctx.send(f"✅ {len(content)} bytes | **{obf_type}**")
    await ctx.send(f"```lua\n{preview}\n```")
    await ctx.send("🔧 Use `.deobf` to deobfuscate")

@bot.command(name='deobf')
async def deobfuscate(ctx):
    if ctx.author.id not in user_scripts:
        await ctx.send("❌ No script. Use `.get` first")
        return
    
    msg = await ctx.send("🔧 Deobfuscating... (this may take up to 45 seconds)")
    
    try:
        original = user_scripts[ctx.author.id]
        
        result, obf_type, changed = await full_deobfuscate(original)
        
        if not changed or len(result) == len(original):
            await msg.edit(content=f"⚠️ Could not deobfuscate **{obf_type}**. The script may require manual analysis.")
            return
        
        await msg.edit(content="✅ Deobfuscation complete!")
        
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
        await msg.edit(content="❌ Deobfuscation timed out after 45 seconds.")
    except Exception as e:
        await msg.edit(content=f"❌ Error: {str(e)[:100]}")
        print(f"Error: {e}")

@bot.command(name='detect')
async def detect_only(ctx):
    if ctx.author.id not in user_scripts:
        await ctx.send("❌ No script. Use `.get` first")
        return
    
    content = user_scripts[ctx.author.id]
    obf_type = detect_obfuscator(content)
    await ctx.send(f"🔍 **{obf_type}**")

@bot.event
async def on_ready():
    print(f"✅ Lunr Bot ready - {bot.user}")
    print(f"📡 Commands: .get, .deobf, .detect")

if __name__ == "__main__":
    bot.run(TOKEN)
