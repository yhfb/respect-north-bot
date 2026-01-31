import discord
from discord.ext import commands
import os
import aiohttp
import asyncio
import logging
import sqlite3
import json
import io
import urllib.parse
from flask import Flask
from threading import Thread

# --- الإعدادات الأساسية ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger('RespectNorthBot')

TOKEN = os.getenv('DISCORD_TOKEN')
GROQ_API_KEY = os.getenv('GROQ_API_KEY')
CF_ACCOUNT_ID = os.getenv('CLOUDFLARE_ACCOUNT_ID')
CF_API_TOKEN = os.getenv('CLOUDFLARE_API_TOKEN')

# موديلات Groq المتاحة (تم تحديثها للموديلات الحالية)
GROQ_MODELS = [
    "llama-3.3-70b-specdec",
    "llama-3.1-8b-instant",
    "gemma2-9b-it"
]

# --- قاعدة البيانات ---
DB_PATH = 'data/bot_database.db'
os.makedirs('data', exist_ok=True)

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS history (thread_id TEXT PRIMARY KEY, messages TEXT)''')
    conn.commit()
    conn.close()

def get_setting(key, default=None):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT value FROM settings WHERE key=?", (key,))
    res = c.fetchone()
    conn.close()
    return res[0] if res else default

def set_setting(key, value):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(value)))
    conn.commit()
    conn.close()

init_db()

# --- إعدادات البوت ---
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# --- نظام توليد الصور (Cloudflare AI) ---
async def generate_image_cf(prompt):
    if not CF_ACCOUNT_ID or not CF_API_TOKEN:
        # Fallback to Pollinations if CF is not configured
        encoded = urllib.parse.quote(prompt)
        return f"https://image.pollinations.ai/prompt/{encoded}?width=1024&height=1024&nologo=true&model=flux"
    
    url = f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT_ID}/ai/run/@cf/black-forest-labs/flux-1-schnell"
    headers = {"Authorization": f"Bearer {CF_API_TOKEN}"}
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json={"prompt": prompt}, timeout=40) as resp:
                if resp.status == 200:
                    return await resp.read()
                else:
                    logger.error(f"Cloudflare AI Error: {resp.status}")
                    return None
    except Exception as e:
        logger.error(f"Image Generation Exception: {e}")
        return None

# --- نظام الدردشة (Groq) ---
async def get_chat_response(thread_id, user_input):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT messages FROM history WHERE thread_id=?", (thread_id,))
    res = c.fetchone()
    history = json.loads(res[0]) if res else []
    
    history.append({"role": "user", "content": user_input})
    if len(history) > 15: history = history[-15:]
    
    # نظام الهوية الذكي: يذكر المبرمج فقط عند السؤال أو في أول رسالة
    identity_keywords = ["من برمجك", "من صنعك", "من المبرمج", "مين سواك", "who made you", "who programmed you"]
    is_asking_identity = any(kw in user_input.lower() for kw in identity_keywords)
    
    system_prompt = (
        "أنت ذكاء اصطناعي متطور تخدم في سيرفر 'ريسبكت الشمال'. "
        "تحدث باللغة العربية الفصحى بأسلوب فخم ومهذب. "
    )
    
    if is_asking_identity or len(history) <= 2:
        system_prompt += (
            "يجب أن تذكر بفخر: 'تمت برمجتي وتطويري بواسطة الإدارة العليا لسيرفر ريسبكت الشمال 🛡️، "
            "وبإشراف مباشر من المبدع king to day 👑. أنا هنا لخدمتكم! ✨'"
        )
    
    messages = [{"role": "system", "content": system_prompt}] + history
    
    for model in GROQ_MODELS:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
                    json={"model": model, "messages": messages, "temperature": 0.7},
                    timeout=15
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        ai_msg = data['choices'][0]['message']['content']
                        history.append({"role": "assistant", "content": ai_msg})
                        c.execute("INSERT OR REPLACE INTO history (thread_id, messages) VALUES (?, ?)", 
                                  (thread_id, json.dumps(history)))
                        conn.commit()
                        conn.close()
                        return ai_msg
                    elif resp.status == 429:
                        await asyncio.sleep(1)
                        continue
        except Exception as e:
            logger.error(f"Error with model {model}: {e}")
            continue
    
    conn.close()
    return "عذراً، أواجه ضغطاً حالياً. حاول مجدداً بعد دقيقة. 🛡️"

# --- أحداث البوت ---
@bot.event
async def on_ready():
    logger.info(f"🚀 Logged in as {bot.user}")
    await bot.change_presence(activity=discord.Game(name="خدمة ريسبكت الشمال 🛡️"))

@bot.command()
async def set_ai(ctx):
    if not ctx.author.guild_permissions.administrator:
        return await ctx.send("⚠️ هذا الأمر للمسؤولين فقط.")
    set_setting('ai_channel', ctx.channel.id)
    await ctx.send(f"✅ تم تفعيل الذكاء الاصطناعي في: {ctx.channel.mention} 🛡️")

@bot.event
async def on_message(message):
    if message.author.bot: return
    
    ai_channel_id = get_setting('ai_channel')
    if ai_channel_id and message.channel.id == int(ai_channel_id):
        # إنشاء ثريد تلقائي إذا لم يكن موجوداً
        if not isinstance(message.channel, discord.Thread):
            try:
                thread = await message.create_thread(name=f"🔒 {message.author.display_name}", auto_archive_duration=60)
                await thread.send(f"مرحباً {message.author.mention}! أنا ذكاء ريسبكت الشمال، كيف يمكنني مساعدتك اليوم؟ 🛡️")
            except: pass
            return

    if isinstance(message.channel, discord.Thread) and message.channel.owner_id == bot.user.id:
        image_keywords = ["ارسم", "صورة", "تخيل", "draw", "image", "imagine"]
        is_image_request = any(word in message.content.lower() for word in image_keywords)
        
        async with message.channel.typing():
            if is_image_request:
                prompt = message.content
                for word in image_keywords: prompt = prompt.replace(word, "")
                
                result = await generate_image_cf(prompt.strip())
                if isinstance(result, bytes):
                    file = discord.File(io.BytesIO(result), filename="north_ai.png")
                    embed = discord.Embed(title="✨ نتيجة الخيال", color=0x2b2d31)
                    embed.set_image(url="attachment://north_ai.png")
                    embed.set_footer(text="بواسطة ذكاء ريسبكت الشمال 🛡️")
                    await message.reply(embed=embed, file=file)
                elif isinstance(result, str): # URL Fallback
                    embed = discord.Embed(title="✨ نتيجة الخيال", color=0x2b2d31)
                    embed.set_image(url=result)
                    embed.set_footer(text="بواسطة ذكاء ريسبكت الشمال 🛡️")
                    await message.reply(embed=embed)
                else:
                    await message.reply("❌ عذراً، فشلت في توليد الصورة حالياً.")
            else:
                response = await get_chat_response(str(message.channel.id), message.content)
                if len(response) > 2000:
                    for i in range(0, len(response), 2000): await message.reply(response[i:i+2000])
                else:
                    await message.reply(response)
    
    await bot.process_commands(message)

# --- Flask ---
app = Flask('')
@app.route('/')
def home(): return "Bot is Online!"

def run_flask(): app.run(host='0.0.0.0', port=8080)

if __name__ == "__main__":
    Thread(target=run_flask, daemon=True).start()
    bot.run(TOKEN)
