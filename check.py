import os
import time
import requests

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")

# الكلمات والأفلام المستهدفة مع الصالات المطلوبة
TARGETS = [
    {"movie": "Dune Part Three", "hall": "IMAX", "search_keyword": "dune"},
    {"movie": "Avengers Doomsday", "hall": "MAX", "search_keyword": "avengers"}
]

def send_telegram_message(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }
    try:
        response = requests.post(url, json=payload, timeout=20)
        response.raise_for_status()
        print("✅ تم إرسال التنبيه المفصل إلى تليجرام بنجاح!")
    except Exception as e:
        print(f"❌ خطأ في إرسال رسالة تليجرام: {e}")

def check_booking():
    # سنقوم بفحص الصفحة الرئيسية أو صفحة الأفلام المباشرة لفوكس مصر
    url = "https://egy.voxcinemas.com/movies"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
    }
    
    try:
        print("⏳ جاري فحص صفحة فوكس سينما مصر للبحث عن المواعيد...")
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        page_content = response.text.lower()
        
        for target in TARGETS:
            movie_name = target["movie"]
            hall_type = target["hall"]
            keyword = target["search_keyword"]
            
            # التحقق مما إذا كان الفيلم والصالة قد ظهرا في محتوى الصفحة
            if keyword in page_content and hall_type.lower() in page_content:
                alert_msg = (
                    f"🚨 **تنبيه عروض حصرية!** 🚨\n\n"
                    f"🎬 الفيلم: **{movie_name}**\n"
                    f"🎦 الصالة المتاحة: **{hall_type}**\n\n"
                    f"✨ التذاكر والمواعيد ظهرت على السيستم الآن!\n"
                    f"🔗 [اضغط هنا لاختيار الميعاد والحجز فوراً](https://egy.voxcinemas.com/movies)"
                )
                send_telegram_message(alert_msg)
                time.sleep(2)
                print(f"✅ تم رصد صالة {hall_type} لفيلم {movie_name} وإرسال التنبيه!")
            else:
                print(f"⏳ فيلم '{movie_name}' أو صالة '{hall_type}' لسه مانزلش لها جدول مواعيد.")

    except Exception as e:
        print(f"❌ خطأ أثناء فحص المواعيد: {e}")

if __name__ == "__main__":
    check_booking()
  
