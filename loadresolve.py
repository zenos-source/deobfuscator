import re
import aiohttp
import asyncio

async def resolve_loadstring_chain(content, depth=0):
    if depth > 5:
        return content
    
    patterns = [
        r'loadstring\(game:HttpGet\(["\']([^"\']+)["\']\)\)\s*\(?\)?',
        r'loadstring\(game:HttpGetAsync\(["\']([^"\']+)["\']\)\)',
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
                                f'--[[ resolved from {url} ]]\n{fetched}\n--[[ end resolve ]]'
                            )
                            content = await resolve_loadstring_chain(content, depth + 1)
                except:
                    pass
    
    return content
