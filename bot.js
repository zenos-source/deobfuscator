const { Client, GatewayIntentBits } = require("discord.js");
const fetch = require("node-fetch");

const TOKEN = process.env.DISCORD_TOKEN;

if (!TOKEN) {
    console.error("Missing DISCORD_TOKEN");
    process.exit(1);
}

class LunrDeobfuscator {
    constructor(code) {
        this.code = code;
        this.result = "";
        this.obfuscatorType = "Unknown";
        this.stats = { stringsDecoded: 0, patterns: 0 };
    }

    detect() {
        const c = this.code.toLowerCase();
        if (/moonsec/.test(c) || /local\s+[a-z_]\s*=\s*\{[^}]*["'][^"']*["']/.test(c)) return "MoonSec";
        if (/wearedevs/.test(c)) return "WeAreDevs";
        if (/ironbrew/.test(c) || /getfenv/.test(c)) return "IronBrew";
        return "Unknown";
    }

    decodeOctal(str) {
        return str.replace(/\\(\d{3})/g, (_, oct) => {
            if (/[0-7]{3}/.test(oct)) {
                this.stats.patterns++;
                return String.fromCharCode(parseInt(oct, 8));
            }
            return `\\${oct}`;
        });
    }

    decodeHex(str) {
        return str.replace(/\\x([0-9a-fA-F]{2})/g, (_, hex) => {
            this.stats.patterns++;
            return String.fromCharCode(parseInt(hex, 16));
        });
    }

    decodeStringChar(str) {
        return str.replace(/string\.char\(([^)]+)\)/g, (_, nums) => {
            const chars = nums.split(",").map(n => {
                const num = parseInt(n.trim());
                return num ? String.fromCharCode(num) : "";
            });
            this.stats.stringsDecoded++;
            return `"${chars.join("")}"`;
        });
    }

    extractStringTable(code) {
        const tableMatch = code.match(/local\s+([a-z_]+)\s*=\s*\{([^}]+)\}/);
        if (!tableMatch) return code;
        
        const varName = tableMatch[1];
        const strings = tableMatch[2].match(/"([^"]*)"/g);
        
        if (!strings) return code;
        
        let result = code;
        for (let i = 0; i < strings.length; i++) {
            const decoded = this.decodeOctal(this.decodeHex(strings[i].slice(1, -1)));
            result = result.replace(new RegExp(`${varName}\\[${i + 1}\\]`, "g"), `"${decoded}"`);
            this.stats.stringsDecoded++;
        }
        
        result = result.replace(new RegExp(`local ${varName} = \\{[^}]+\\};?`, "g"), "");
        return result;
    }

    deobfuscate() {
        this.obfuscatorType = this.detect();
        
        let result = this.code;
        result = this.decodeOctal(result);
        result = this.decodeHex(result);
        result = this.decodeStringChar(result);
        
        if (this.obfuscatorType === "MoonSec" || this.obfuscatorType === "WeAreDevs") {
            result = this.extractStringTable(result);
        }
        
        result = result.replace(/\n\s*\n/g, "\n").trim();
        result = result.replace(/;\s*\n/g, "\n");
        
        this.result = result;
        return { success: true, result: this.result };
    }
}

const client = new Client({
    intents: [GatewayIntentBits.Guilds, GatewayIntentBits.GuildMessages, GatewayIntentBits.MessageContent]
});

const userScripts = new Map();

async function fetchUrl(url) {
    try {
        const res = await fetch(url, { headers: { "User-Agent": "Lunr-Bot/1.0" } });
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

client.once("ready", async () => {
    console.log(`✅ Lunr Bot ready - ${client.user.tag}`);
    console.log(`📡 Commands: .get, .deobf, .detect`);
});

client.on("messageCreate", async (message) => {
    if (message.author.bot) return;
    if (!message.content.startsWith(".")) return;
    
    const args = message.content.slice(1).trim().split(/ +/);
    const command = args.shift().toLowerCase();
    
    if (command === "get") {
        const target = args.join(" ");
        if (!target) return message.reply("❌ Usage: `.get <url|asset_id>`");
        
        await message.reply("🔍 Fetching...");
        const content = await fetchScript(target);
        
        if (!content) return message.reply("❌ Could not fetch script");
        
        const deobf = new LunrDeobfuscator(content);
        const obfType = deobf.detect();
        
        userScripts.set(message.author.id, content);
        
        const preview = content.slice(0, 400) + (content.length > 400 ? "..." : "");
        await message.reply(`✅ ${content.length} bytes | **${obfType}**\n\`\`\`lua\n${preview}\n\`\`\`\n🔧 Use \`.deobf\` to deobfuscate`);
    }
    
    if (command === "deobf") {
        const content = userScripts.get(message.author.id);
        if (!content) return message.reply("❌ No script. Use `.get` first");
        
        const msg = await message.reply("🔧 Deobfuscating...");
        
        try {
            const deobf = new LunrDeobfuscator(content);
            const result = deobf.deobfuscate();
            
            if (result.result === content) {
                await msg.edit(`⚠️ Could not deobfuscate **${deobf.obfuscatorType}**.`);
                return;
            }
            
            await msg.edit("✅ Complete!");
            
            if (result.result.length > 1900) {
                await message.reply({ files: [{ attachment: Buffer.from(result.result, "utf-8"), name: "deobfuscated.lua" }] });
            } else {
                await message.reply(`\`\`\`lua\n${result.result}\n\`\`\``);
            }
            
            await msg.delete();
            userScripts.delete(message.author.id);
        } catch (error) {
            await msg.edit(`❌ Error: ${error.message}`);
        }
    }
    
    if (command === "detect") {
        const content = userScripts.get(message.author.id);
        if (!content) return message.reply("❌ No script. Use `.get` first");
        
        const deobf = new LunrDeobfuscator(content);
        await message.reply(`🔍 **Obfuscator:** ${deobf.detect()}`);
    }
});

client.login(TOKEN);
