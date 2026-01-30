import discord
from discord.ext import commands
import os
import logging
import urllib.parse
import random
import requests
import io
from groq import Groq
from flask import Flask
from threading import Thread

# إعداد السجلات
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('RespectNorthBot')

# --- المفاتيح ---
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
HF_API_KEY = os.getenv("HF_API_KEY")

# تهيئة العملاء
client_groq = Groq(api_key=GROQ_API_KEY)

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.messages = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

# --- خادم الويب للأبتايم ---
app = Flask('')
@app.route('/')
def home(): return "I'm alive!"
def run_web(): app.run(host='0.0.0.0', port=8080)
def keep_alive(): Thread(target=run_web).start()

AI_CHANNEL_ID = None
thread_history = {}

@bot.event
async def on_ready():
    logger.info(f'🚀 {bot.user.name} Ready!')

@bot.command()
async def set_ai(ctx, channel: discord.TextChannel = None):
    if not ctx.author.guild_permissions.administrator: return
    global AI_CHANNEL_ID
    AI_CHANNEL_ID = (channel or ctx.channel).id
    await ctx.send("✅ تم تفعيل الذكاء الاصطناعي بنجاح.")

@bot.event
async def on_message(message):
    if message.author == bot.user: return
    await bot.process_commands(message)

    if AI_CHANNEL_ID and message.channel.id == AI_CHANNEL_ID:
        if not isinstance(message.channel, discord.Thread):
            try: await message.create_thread(name=f"🔒 {message.author.display_name}", auto_archive_duration=60)
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
                        t_res = client_groq.chat.completions.create(
                            model="llama-3.3-70b-versatile",
                            messages=[{"role":"system","content":"Output ONLY a detailed English image prompt based on the user request."},{"role":"user","content":prompt_raw}]
                        )
                        enhanced_prompt = t_res.choices[0].message.content
                    except: enhanced_prompt = prompt_raw

                    API_URL = "https://api-inference.huggingface.co/models/black-forest-labs/FLUX.1-schnell"
                    headers = {"Authorization": f"Bearer {HF_API_KEY}"}
                    
                    try:
                        response = requests.post(API_URL, headers=headers, json={"inputs": enhanced_prompt}, timeout=60)
                        if response.status_code == 200:
                            await message.reply(file=discord.File(io.BytesIO(response.content), filename="result.png"))
                        else:
                            seed = random.randint(1, 10**9)
                            await message.reply(f"https://image.pollinations.ai/prompt/{urllib.parse.quote(enhanced_prompt)}?width=1024&height=1024&seed={seed}&model=flux&nologo=true")
                    except: pass
                
                else:
                    t_id = message.channel.id
                    if t_id not in thread_history:
                        thread_history[t_id] = [{"role": "system", "content": "أنت مساعد ذكي وخبير لسيرفر ريسبكت الشمال. يجب أن تكون جميع ردودك باللغة العربية الفصحى فقط وبأسلوب طبيعي وواضح. يمنع استخدام أي لغات أخرى في الردود إلا إذا طلب المستخدم ذلك صراحة."}]
                    
                    thread_history[t_id].append({"role": "user", "content": user_input})
                    
                    try:
                        response = client_groq.chat.completions.create(
                            model="llama-3.3-70b-versatile",
                            messages=thread_history[t_id][-10:],
                            temperature=0.7
                        )
                        reply = response.choices[0].message.content
                        thread_history[t_id].append({"role": "assistant", "content": reply})
                        await message.reply(reply)
                    except:
                        await message.reply("⚠️ عذراً، واجهت مشكلة بسيطة.")

            except Exception as e:
                logger.error(f"Error: {e}")
                await message.reply("⚠️ حدث خطأ، يرجى المحاولة مرة أخرى.")

if __name__ == "__main__":
    keep_alive()
    bot.run(DISCORD_TOKEN)
