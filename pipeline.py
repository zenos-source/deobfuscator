import subprocess
import tempfile
import os
from detect import detect_obfuscator
from hexdecode import decode_hex_string
from loadresolve import resolve_loadstring_chain
import asyncio

LURAPH_JAR = "LuraphDevirtualizer.jar"
UNLUAC_JAR = "unluac.jar"
DE4LUA_DIR = "De4Lua"

async def run_luraph_deobf(input_path, output_path):
    luac_path = output_path.replace('.lua', '.luac')
    
    result1 = subprocess.run(
        ['java', '-jar', LURAPH_JAR, '-i', input_path, '-o', luac_path],
        capture_output=True
    )
    if result1.returncode != 0:
        return False
    
    result2 = subprocess.run(
        ['java', '-jar', UNLUAC_JAR, luac_path],
        capture_output=True
    )
    if result2.returncode != 0:
        return False
    
    with open(output_path, 'w') as f:
        f.write(result2.stdout.decode())
    return True

async def run_de4lua(input_path, output_path):
    result = subprocess.run(
        ['npm', 'run', 'start', '--', input_path, output_path],
        cwd=DE4LUA_DIR,
        capture_output=True
    )
    return result.returncode == 0

async def full_deobfuscation(script_content):
    print("Decoding hex...")
    script_content = decode_hex_string(script_content)
    
    print("Resolving loadstring chains...")
    script_content = await resolve_loadstring_chain(script_content)
    
    detection = detect_obfuscator(script_content)
    print(f"Detected: {detection['obfuscator']} ({detection['confidence']}%)")
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.lua', delete=False) as f:
        f.write(script_content)
        input_path = f.name
    
    output_path = tempfile.NamedTemporaryFile(mode='w', suffix='.lua', delete=False).name
    
    try:
        if detection['obfuscator'] == 'luraph' and detection['confidence'] > 50:
            print("Running Luraph devirtualizer...")
            success = await run_luraph_deobf(input_path, output_path)
        else:
            print("Running De4Lua...")
            success = await run_de4lua(input_path, output_path)
        
        if not success:
            return script_content
        
        with open(output_path, 'r') as f:
            result = f.read()
        return result if result else script_content
    finally:
        for path in [input_path, output_path]:
            if os.path.exists(path):
                os.unlink(path)
