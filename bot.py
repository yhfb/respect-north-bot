import discord
from discord.ext import commands
import os
import logging
import urllib.parse
import random
import requests
import io
import traceback
from groq import Groq
from flask import Flask
from threading import Thread
from dotenv import load_dotenv

# تحميل متغيرات البيئة من ملف .env إذا وجد (للتطوير المحلي)
load_dotenv()

# إعداد السجلات بشكل أكثر تفصيلاً
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('RespectNorthBot')

# --- المفاتيح ---
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
HF_API_KEY = os.getenv("HF_API_KEY")

# التحقق من وجود المفاتيح الأساسية
if not DISCORD_TOKEN:
    logger.error("❌ DISCORD_TOKEN is missing!")
if not GROQ_API_KEY:
    logger.error("❌ GROQ_API_KEY is missing!")

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
def home(): 
    return "Respect North Bot is Alive and Running!"

def run_web():
    try:
        app.run(host='0.0.0.0', port=8080)
    except Exception as e:
        logger.error(f"Web server error: {e}")

def keep_alive():
    t = Thread(target=run_web)
    t.daemon = True
    t.start()

AI_CHANNEL_ID = None
thread_history = {}

@bot.event
async def on_ready():
    logger.info(f'🚀 Logged in as {bot.user.name} (ID: {bot.user.id})')
    logger.info('------')
    await bot.change_presence(activity=discord.Game(name="في خدمة ريسبكت الشمال"))

@bot.command()
async def set_ai(ctx, channel: discord.TextChannel = None):
    """تحديد الروم المخصصة للذكاء الاصطناعي"""
    if not ctx.author.guild_permissions.administrator:
        return await ctx.send("⚠️ عذراً، هذا الأمر مخصص للمسؤولين فقط.")
    
    global AI_CHANNEL_ID
    target_channel = channel or ctx.channel
    AI_CHANNEL_ID = target_channel.id
    await ctx.send(f"✅ تم تفعيل الذكاء الاصطناعي في {target_channel.mention} بنجاح.")

@bot.event
async def on_message(message):
    if message.author == bot.user:
        return

    # معالجة الأوامر أولاً
    await bot.process_commands(message)

    # التحقق من الروم المخصصة للذكاء الاصطناعي
    if AI_CHANNEL_ID and message.channel.id == AI_CHANNEL_ID:
        # إذا لم تكن الرسالة داخل Thread، قم بإنشاء واحد
        if not isinstance(message.channel, discord.Thread):
            try:
                thread = await message.create_thread(
                    name=f"🔒 {message.author.display_name}",
                    auto_archive_duration=60
                )
                logger.info(f"Created new thread for {message.author.display_name}")
            except Exception as e:
                logger.error(f"Failed to create thread: {e}")
            return

    # معالجة الرسائل داخل الـ Threads التي يملكها البوت
    if isinstance(message.channel, discord.Thread) and message.channel.owner_id == bot.user.id:
        async with message.channel.typing():
            try:
                user_input = message.content.strip()
                if not user_input:
                    return

                # --- نظام توليد الصور ---
                img_keywords = ["صورة", "ارسم", "image", "draw", "توليد", "صمم", "تخيل"]
                if any(user_input.lower().startswith(kw) for kw in img_keywords):
                    prompt_raw = user_input
                    for kw in img_keywords:
                        if user_input.lower().startswith(kw):
                            prompt_raw = user_input[len(kw):].strip()
                            break
                    
                    if not prompt_raw:
                        return await message.reply("يرجى كتابة وصف للصورة التي تريدها.")

                    # تحسين الـ Prompt باستخدام Groq
                    try:
                        t_res = client_groq.chat.completions.create(
                            model="llama-3.3-70b-versatile",
                            messages=[
                                {"role": "system", "content": "You are a professional prompt engineer. Convert the user's request into a highly detailed, artistic English image prompt for FLUX model. Output ONLY the prompt text."},
                                {"role": "user", "content": prompt_raw}
                            ]
                        )
                        enhanced_prompt = t_res.choices[0].message.content
                    except Exception as e:
                        logger.warning(f"Prompt enhancement failed: {e}")
                        enhanced_prompt = prompt_raw

                    # محاولة التوليد عبر Hugging Face
                    API_URL = "https://api-inference.huggingface.co/models/black-forest-labs/FLUX.1-schnell"
                    headers = {"Authorization": f"Bearer {HF_API_KEY}"}
                    
                    success = False
                    if HF_API_KEY:
                        try:
                            response = requests.post(API_URL, headers=headers, json={"inputs": enhanced_prompt}, timeout=60)
                            if response.status_code == 200:
                                await message.reply(file=discord.File(io.BytesIO(response.content), filename="result.png"))
                                success = True
                        except Exception as e:
                            logger.error(f"Hugging Face generation error: {e}")

                    # البديل (Fallback) في حال فشل HF أو عدم وجود مفتاح
                    if not success:
                        try:
                            seed = random.randint(1, 10**9)
                            image_url = f"https://image.pollinations.ai/prompt/{urllib.parse.quote(enhanced_prompt)}?width=1024&height=1024&seed={seed}&model=flux&nologo=true"
                            await message.reply(image_url)
                        except Exception as e:
                            logger.error(f"Fallback generation error: {e}")
                            await message.reply("⚠️ عذراً، واجهت مشكلة في توليد الصورة.")
                
                # --- نظام الدردشة ---
                else:
                    t_id = message.channel.id
                    if t_id not in thread_history:
                        thread_history[t_id] = [
                            {"role": "system", "content": "أنت مساعد ذكي وخبير لسيرفر ريسبكت الشمال. يجب أن تكون جميع ردودك باللغة العربية الفصحى فقط وبأسلوب طبيعي وواضح. يمنع استخدام أي لغات أخرى في الردود إلا إذا طلب المستخدم ذلك صراحة."}
                        ]
                    
                    thread_history[t_id].append({"role": "user", "content": user_input})
                    
                    # الحفاظ على آخر 15 رسالة للسياق (زيادة من 10)
                    if len(thread_history[t_id]) > 16:
                        thread_history[t_id] = [thread_history[t_id][0]] + thread_history[t_id][-15:]
                    
                    try:
                        response = client_groq.chat.completions.create(
                            model="llama-3.3-70b-versatile",
                            messages=thread_history[t_id],
                            temperature=0.7
                        )
                        reply = response.choices[0].message.content
                        thread_history[t_id].append({"role": "assistant", "content": reply})
                        
                        # تقسيم الرسائل الطويلة إذا لزم الأمر
                        if len(reply) > 2000:
                            for i in range(0, len(reply), 2000):
                                await message.reply(reply[i:i+2000])
                        else:
                            await message.reply(reply)
                            
                    except Exception as e:
                        logger.error(f"Groq Chat Error: {e}")
                        await message.reply("⚠️ عذراً، واجهت مشكلة في معالجة طلبك.")

            except Exception as e:
                logger.error(f"General Error: {e}")
                logger.error(traceback.format_exc())
                await message.reply("⚠️ حدث خطأ غير متوقع، يرجى المحاولة مرة أخرى.")

if __name__ == "__main__":
    if not DISCORD_TOKEN:
        print("❌ Error: DISCORD_TOKEN environment variable is not set.")
    else:
        keep_alive()
        bot.run(DISCORD_TOKEN)
