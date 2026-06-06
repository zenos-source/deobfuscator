import re

def decode_hex_string(content):
    result = content
    hex_pattern = r'["\']([0-9a-fA-F]{20,})["\']'
    
    for match in re.finditer(hex_pattern, content):
        hex_str = match.group(1)
        try:
            decoded = bytes.fromhex(hex_str).decode('utf-8', errors='ignore')
            result = result.replace(f'"{hex_str}"', f'--[[hex decoded]]\n"{decoded}"')
        except:
            pass
    
    xor_chars = re.findall(r'string\.char\(0x([0-9a-fA-F]{2})\)', content)
    if xor_chars:
        decoded = ''.join(chr(int(c, 16)) for c in xor_chars)
        result = f'--[[ XOR decoded: {decoded[:200]} ]]\n{result}'
    
    return result
