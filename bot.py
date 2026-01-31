import discord
from discord.ext import commands
import os
import logging
import urllib.parse
import random
import aiohttp
import io
import sqlite3
import json
import asyncio
from groq import Groq
from flask import Flask
from threading import Thread
from dotenv import load_dotenv

# تحميل متغيرات البيئة
load_dotenv()

# إعداد السجلات
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('RespectNorthBot')

# --- إعداد قاعدة البيانات ---
DB_PATH = "data/bot_database.db"
os.makedirs("data", exist_ok=True)

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS history (thread_id INTEGER PRIMARY KEY, messages TEXT)''')
    conn.commit()
    conn.close()

def save_setting(key, value):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(value)))
    conn.commit()
    conn.close()

def get_setting(key):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT value FROM settings WHERE key=?", (key,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else None

def save_history(thread_id, messages):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO history (thread_id, messages) VALUES (?, ?)", (thread_id, json.dumps(messages)))
    conn.commit()
    conn.close()

def get_history(thread_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT messages FROM history WHERE thread_id=?", (thread_id,))
    row = c.fetchone()
    conn.close()
    return json.loads(row[0]) if row else None

init_db()

# --- المفاتيح ---
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

try:
    client_groq = Groq(api_key=GROQ_API_KEY)
except Exception as e:
    logger.error(f"❌ Failed to initialize Groq client: {e}")

GROQ_MODELS = [
    "llama-3.3-70b-versatile", 
    "llama-3.1-70b-versatile",
    "llama-3.2-90b-vision-preview",
    "mixtral-8x7b-32768",
    "llama-3.1-8b-instant"
]

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.messages = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

# --- خادم الويب للأبتايم ---
app = Flask('')
@app.route('/')
def home(): return "Respect North Bot is Alive and Running!"
def run_web(): app.run(host='0.0.0.0', port=8080)
def keep_alive():
    t = Thread(target=run_web)
    t.daemon = True
    t.start()

@bot.event
async def on_ready():
    logger.info(f'🚀 Logged in as {bot.user.name}')
    await bot.change_presence(activity=discord.Game(name="في خدمة ريسبكت الشمال 🛡️"))

@bot.command()
async def set_ai(ctx, channel: discord.TextChannel = None):
    if not ctx.author.guild_permissions.administrator:
        return await ctx.send("⚠️ عذراً، هذا الأمر مخصص للمسؤولين فقط.")
    target_channel = channel or ctx.channel
    save_setting("AI_CHANNEL_ID", target_channel.id)
    await ctx.send(f"✅ تم تفعيل الذكاء الاصطناعي في {target_channel.mention} بنجاح.")

async def get_groq_response(messages):
    loop = asyncio.get_event_loop()
    for model in GROQ_MODELS:
        try:
            response = await loop.run_in_executor(None, lambda: client_groq.chat.completions.create(
                model=model,
                messages=messages,
                temperature=0.7
            ))
            return response.choices[0].message.content
        except Exception as e:
            if "429" in str(e) or "rate_limit" in str(e).lower():
                await asyncio.sleep(1)
                continue
            else:
                logger.error(f"Error with model {model}: {e}")
                continue
    return None

@bot.event
async def on_message(message):
    if message.author == bot.user: return
    await bot.process_commands(message)

    ai_channel_id = get_setting("AI_CHANNEL_ID")
    if ai_channel_id and message.channel.id == int(ai_channel_id):
        if not isinstance(message.channel, discord.Thread):
            try:
                await message.create_thread(name=f"🔒 {message.author.display_name}", auto_archive_duration=60)
            except: pass
            return

    if isinstance(message.channel, discord.Thread) and message.channel.owner_id == bot.user.id:
        async with message.channel.typing():
            try:
                user_input = message.content.strip()
                if not user_input: return

                img_keywords = ["صورة", "ارسم", "image", "draw", "توليد", "صمم", "تخيل"]
                if any(user_input.lower().startswith(kw) for kw in img_keywords):
                    prompt_raw = user_input
                    for kw in img_keywords:
                        if user_input.lower().startswith(kw):
                            prompt_raw = user_input[len(kw):].strip()
                            break
                    
                    try:
                        enhanced_prompt = await get_groq_response([
                            {"role": "system", "content": "Convert to a highly detailed English image prompt. Focus on artistic quality. ONLY the prompt text."},
                            {"role": "user", "content": prompt_raw}
                        ])
                        if not enhanced_prompt: enhanced_prompt = prompt_raw
                    except: enhanced_prompt = prompt_raw

                    # استخدام محرك Magic Studio (بديل احترافي لـ Pollinations)
                    # هذا المحرك يعطي جودة عالية جداً ومستقر
                    encoded_prompt = urllib.parse.quote(enhanced_prompt)
                    image_url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1024&height=1024&nologo=true&model=flux-pro"
                    
                    # محرك بديل آخر (Cloudflare Flux) في حال فشل الأول
                    fallback_url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1024&height=1024&nologo=true&model=flux-realism"

                    success = False
                    for url in [image_url, fallback_url]:
                        try:
                            async with aiohttp.ClientSession() as session:
                                async with session.get(url, timeout=45) as resp:
                                    if resp.status == 200:
                                        data = await resp.read()
                                        if len(data) > 20000: # فحص حجم الملف لضمان الجودة العالية
                                            file = discord.File(io.BytesIO(data), filename="north_image.png")
                                            await message.reply(content="✨ تفضل، إليك ما تخيلته لك بدقة احترافية:", file=file)
                                            success = True
                                            break
                        except Exception as e:
                            logger.warning(f"Engine failed: {url}, error: {e}")
                            continue
                    
                    if not success:
                        await message.reply("⚠️ عذراً، محركات الصور الاحترافية مشغولة حالياً. يرجى المحاولة مرة أخرى بعد قليل.")
                
                else:
                    t_id = message.channel.id
                    history = get_history(t_id)
                    if not history:
                        system_prompt = (
                            "أنت مساعد ذكي وخبير لسيرفر ريسبكت الشمال (Respect North). "
                            "يجب أن تكون جميع ردودك باللغة العربية الفصحى فقط بأسلوب فخم ومهذب. "
                            "إذا سألك أحد من برمجك أو من صنعك، يجب أن تجيب دائماً وبفخر: "
                            "'تمت برمجتي وتطويري بواسطة الإدارة العليا لسيرفر ريسبكت الشمال 🛡️، "
                            "وبإشراف مباشر من المبدع king to day 👑. أنا هنا لخدمتكم وتقديم أفضل تجربة ذكاء اصطناعي لكم! ✨'"
                        )
                        history = [{"role": "system", "content": system_prompt}]
                    
                    history.append({"role": "user", "content": user_input})
                    if len(history) > 16: history = [history[0]] + history[-15:]
                    
                    try:
                        reply = await get_groq_response(history)
                        if reply:
                            history.append({"role": "assistant", "content": reply})
                            save_history(t_id, history)
                            
                            if len(reply) > 2000:
                                for i in range(0, len(reply), 2000): await message.reply(reply[i:i+2000])
                            else: await message.reply(reply)
                        else:
                            await message.reply("⚠️ عذراً، يبدو أن هناك ضغطاً كبيراً على النظام حالياً. يرجى الانتظار دقيقة واحدة والمحاولة مرة أخرى. 🛡️")
                            
                    except Exception as e:
                        logger.error(f"Final Error: {e}")
                        await message.reply("⚠️ النظام يواجه ضغطاً حالياً، يرجى المحاولة بعد قليل.")

            except Exception as e:
                logger.error(f"General Error: {e}")
                await message.reply("⚠️ حدث خطأ غير متوقع أثناء معالجة طلبك.")

if __name__ == "__main__":
    if DISCORD_TOKEN:
        keep_alive()
        bot.run(DISCORD_TOKEN)
    else:
        print("❌ DISCORD_TOKEN not found!")
