const { Client, GatewayIntentBits, EmbedBuilder } = require("discord.js");
const fetch = require("node-fetch");

const TOKEN = process.env.DISCORD_TOKEN;

if (!TOKEN) {
    console.error("Missing DISCORD_TOKEN");
    process.exit(1);
}

const client = new Client({
    intents: [
        GatewayIntentBits.Guilds,
        GatewayIntentBits.GuildMessages,
        GatewayIntentBits.MessageContent
    ]
});

// Store scripts per user
const userScripts = new Map();

// ============================================================
// DEOBFUSCATOR CLASS
// ============================================================

class LunrDeobfuscator {
    constructor(code) {
        this.code = code;
        this.result = "";
        this.obfuscatorType = "Unknown";
        this.stats = { decoded: 0 };
    }

    detect() {
        const c = this.code.toLowerCase();
        if (/moonsec|local\s+[a-z_]\s*=\s*\{[^}]*["']/.test(c)) return "MoonSec";
        if (/wearedevs/.test(c)) return "WeAreDevs";
        if (/ironbrew|getfenv/.test(c)) return "IronBrew";
        return "Unknown";
    }

    deobfuscate() {
        this.obfuscatorType = this.detect();
        let result = this.code;
        
        // Decode \123 octal
        result = result.replace(/\\(\d{3})/g, (_, oct) => {
            if (/[0-7]{3}/.test(oct)) {
                this.stats.decoded++;
                return String.fromCharCode(parseInt(oct, 8));
            }
            return `\\${oct}`;
        });
        
        // Decode \x48 hex
        result = result.replace(/\\x([0-9a-fA-F]{2})/g, (_, hex) => {
            this.stats.decoded++;
            return String.fromCharCode(parseInt(hex, 16));
        });
        
        // Decode string.char(65,66)
        result = result.replace(/string\.char\(([^)]+)\)/g, (_, nums) => {
            const chars = nums.split(",").map(n => String.fromCharCode(parseInt(n.trim())));
            this.stats.decoded++;
            return `"${chars.join("")}"`;
        });
        
        // Extract and decode string tables
        const tableMatch = result.match(/local\s+([a-z_]+)\s*=\s*\{([^}]+)\}/);
        if (tableMatch) {
            const varName = tableMatch[1];
            const strings = tableMatch[2].match(/"([^"]*)"/g);
            if (strings) {
                strings.forEach((str, i) => {
                    const decoded = str.slice(1, -1).replace(/\\(\d{3})/g, (_, oct) => {
                        return /[0-7]{3}/.test(oct) ? String.fromCharCode(parseInt(oct, 8)) : `\\${oct}`;
                    });
                    result = result.replace(new RegExp(`${varName}\\[${i + 1}\\]`, "g"), `"${decoded}"`);
                    this.stats.decoded++;
                });
                result = result.replace(new RegExp(`local ${varName} = \\{[^}]+\\};?`, "g"), "");
            }
        }
        
        // Cleanup
        result = result.replace(/\n\s*\n/g, "\n").trim();
        result = result.replace(/;\s*\n/g, "\n");
        
        this.result = result;
        return result;
    }
}

// ============================================================
// FETCH FUNCTIONS
// ============================================================

async function fetchUrl(url) {
    try {
        const res = await fetch(url, { headers: { "User-Agent": "Lunr-Bot" } });
        if (res.ok) return await res.text();
    } catch (e) {}
    return null;
}

async function fetchScript(target) {
    if (target.startsWith("http")) return await fetchUrl(target);
    if (/^\d+$/.test(target)) return await fetchUrl(`https://raw.roblox.com/asset/?id=${target}`);
    const urlMatch = target.match(/https?:\/\/[^\s"'\<\>]+/);
    if (urlMatch) return await fetchUrl(urlMatch[0]);
    return null;
}

// ============================================================
// DISCORD COMMANDS
// ============================================================

client.once("ready", () => {
    console.log(`✅ Lunr Bot ready - ${client.user.tag}`);
    console.log(`📡 Commands: .get, .deobf, .detect`);
});

client.on("messageCreate", async (message) => {
    if (message.author.bot) return;
    if (!message.content.startsWith(".")) return;
    
    const args = message.content.slice(1).trim().split(/ +/);
    const command = args.shift().toLowerCase();
    
    // .get command
    if (command === "get") {
        const target = args.join(" ");
        if (!target) return message.reply("❌ Usage: `.get <url|asset_id|loadstring>`");
        
        await message.reply("🔍 Fetching...");
        const content = await fetchScript(target);
        
        if (!content) return message.reply("❌ Could not fetch script");
        
        const deobf = new LunrDeobfuscator(content);
        const obfType = deobf.detect();
        
        userScripts.set(message.author.id, content);
        
        const preview = content.slice(0, 400) + (content.length > 400 ? "..." : "");
        await message.reply(`✅ ${content.length} bytes | **${obfType}**\n\`\`\`lua\n${preview}\n\`\`\`\n🔧 Use \`.deobf\``);
    }
    
    // .deobf command
    if (command === "deobf") {
        const content = userScripts.get(message.author.id);
        if (!content) return message.reply("❌ No script. Use `.get` first");
        
        const msg = await message.reply("🔧 Deobfuscating...");
        
        try {
            const deobf = new LunrDeobfuscator(content);
            const result = deobf.deobfuscate();
            
            if (result === content) {
                await msg.edit(`⚠️ Could not deobfuscate **${deobf.obfuscatorType}**. Script may use advanced VM protection.`);
                return;
            }
            
            await msg.edit("✅ Complete!");
            
            if (result.length > 1900) {
                await message.reply({
                    files: [{ attachment: Buffer.from(result, "utf-8"), name: "deobfuscated.lua" }]
                });
            } else {
                await message.reply(`\`\`\`lua\n${result}\n\`\`\``);
            }
            
            await msg.delete();
            userScripts.delete(message.author.id);
        } catch (error) {
            await msg.edit(`❌ Error: ${error.message}`);
        }
    }
    
    // .detect command
    if (command === "detect") {
        const content = userScripts.get(message.author.id);
        if (!content) return message.reply("❌ No script. Use `.get` first");
        
        const deobf = new LunrDeobfuscator(content);
        await message.reply(`🔍 **${deobf.detect()}**`);
    }
});

client.login(TOKEN);
