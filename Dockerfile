# استخدام نسخة خفيفة من بايثون
FROM python:3.11-slim

# إعداد مجلد العمل
WORKDIR /app

# تثبيت التبعيات الضرورية للنظام
RUN apt-get update && apt-get install -y \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# نسخ ملف المتطلبات وتثبيتها
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# نسخ باقي ملفات المشروع
COPY . .

# فتح المنفذ المستخدم لخادم الأبتايم
EXPOSE 8080

# أمر التشغيل
CMD ["python", "bot.py"]
