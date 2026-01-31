import discord
from discord.ext import commands
import os
import logging
import urllib.parse
import random
import requests
import io
import traceback
import sqlite3
import json
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
    # جدول الإعدادات (مثل ID الروم المخصصة)
    c.execute('''CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)''')
    # جدول ذاكرة المحادثات
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

# تهيئة قاعدة البيانات عند التشغيل
init_db()

# --- المفاتيح ---
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
HF_API_KEY = os.getenv("HF_API_KEY")

# تهيئة العملاء
try:
    client_groq = Groq(api_key=GROQ_API_KEY)
except Exception as e:
    logger.error(f"❌ Failed to initialize Groq client: {e}")

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
    await bot.change_presence(activity=discord.Game(name="في خدمة ريسبكت الشمال"))

@bot.command()
async def set_ai(ctx, channel: discord.TextChannel = None):
    if not ctx.author.guild_permissions.administrator:
        return await ctx.send("⚠️ عذراً، هذا الأمر مخصص للمسؤولين فقط.")
    
    target_channel = channel or ctx.channel
    save_setting("AI_CHANNEL_ID", target_channel.id)
    await ctx.send(f"✅ تم تفعيل الذكاء الاصطناعي في {target_channel.mention} بنجاح.")

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

                # --- نظام توليد الصور ---
                img_keywords = ["صورة", "ارسم", "image", "draw", "توليد", "صمم", "تخيل"]
                if any(user_input.lower().startswith(kw) for kw in img_keywords):
                    prompt_raw = user_input
                    for kw in img_keywords:
                        if user_input.lower().startswith(kw):
                            prompt_raw = user_input[len(kw):].strip()
                            break
                    
                    try:
                        t_res = client_groq.chat.completions.create(
                            model="llama-3.3-70b-versatile",
                            messages=[
                                {"role": "system", "content": "You are a professional prompt engineer. Convert the user's request into a highly detailed English image prompt. Output ONLY the prompt text."},
                                {"role": "user", "content": prompt_raw}
                            ]
                        )
                        enhanced_prompt = t_res.choices[0].message.content
                    except: enhanced_prompt = prompt_raw

                    API_URL = "https://api-inference.huggingface.co/models/black-forest-labs/FLUX.1-schnell"
                    headers = {"Authorization": f"Bearer {HF_API_KEY}"}
                    
                    success = False
                    if HF_API_KEY:
                        try:
                            response = requests.post(API_URL, headers=headers, json={"inputs": enhanced_prompt}, timeout=60)
                            if response.status_code == 200:
                                await message.reply(file=discord.File(io.BytesIO(response.content), filename="result.png"))
                                success = True
                        except: pass

                    if not success:
                        seed = random.randint(1, 10**9)
                        await message.reply(f"https://image.pollinations.ai/prompt/{urllib.parse.quote(enhanced_prompt)}?width=1024&height=1024&seed={seed}&model=flux&nologo=true")
                
                # --- نظام الدردشة ---
                else:
                    t_id = message.channel.id
                    history = get_history(t_id)
                    if not history:
                        history = [{"role": "system", "content": "أنت مساعد ذكي وخبير لسيرفر ريسبكت الشمال. يجب أن تكون جميع ردودك باللغة العربية الفصحى فقط."}]
                    
                    history.append({"role": "user", "content": user_input})
                    if len(history) > 16: history = [history[0]] + history[-15:]
                    
                    try:
                        response = client_groq.chat.completions.create(
                            model="llama-3.3-70b-versatile",
                            messages=history,
                            temperature=0.7
                        )
                        reply = response.choices[0].message.content
                        history.append({"role": "assistant", "content": reply})
                        save_history(t_id, history)
                        
                        if len(reply) > 2000:
                            for i in range(0, len(reply), 2000): await message.reply(reply[i:i+2000])
                        else: await message.reply(reply)
                            
                    except Exception as e:
                        logger.error(f"Groq Error: {e}")
                        await message.reply("⚠️ عذراً، واجهت مشكلة.")

            except Exception as e:
                logger.error(f"General Error: {e}")
                await message.reply("⚠️ حدث خطأ غير متوقع.")

if __name__ == "__main__":
    if DISCORD_TOKEN:
        keep_alive()
        bot.run(DISCORD_TOKEN)
    else:
        print("❌ DISCORD_TOKEN not found!")
