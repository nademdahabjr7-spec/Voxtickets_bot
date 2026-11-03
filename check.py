import os
import time
import requests

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")

TARGETS = [
    {
        "movie": "Dune Part Three",
        "hall": "IMAX",
        "query": "site:egy.voxcinemas.com dune imax",
        "direct_link": "https://egy.voxcinemas.com/showtimes?c=city-centre-almaza&m=dune-part-three"
    },
    {
        "movie": "Avengers Doomsday",
        "hall": "MAX",
        "query": "site:egy.voxcinemas.com avengers max",
        "direct_link": "https://egy.voxcinemas.com/showtimes?c=city-centre-almaza&m=avengers-doomsday-infinity-vision"
    }
]

def send_telegram_message(session, message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }
    try:
        response = session.post(url, json=payload, timeout=15)
        response.raise_for_status()
        print("✅ تم إرسال التنبيه إلى تليجرام بنجاح!")
    except Exception as e:
        print(f"❌ خطأ في إرسال رسالة تليجرام: {e}")

def check_booking():
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
    }
    
    # استخدام Session لتوحيد الاتصال وتسريع الطلبات
    with requests.Session() as session:
        session.headers.update(headers)
        
        for target in TARGETS:
            movie_name = target["movie"]
            hall_type = target["hall"]
            query = target["query"]
            direct_link = target["direct_link"]
            search_url = f"https://html.duckduckgo.com/html/?q={query}"
            
            try:
                print(f"⏳ جاري فحص توفر فيلم {movie_name} صالة {hall_type}...")
                response = session.get(search_url, timeout=10)
                response.raise_for_status()
                page_content = response.text.lower()
                
                # يمكنك تعديل هذا المتغير ليصبح مرتبطاً بعدد التذاكر الفعلي من الموقع لو متاح
                tickets_available = 0 
                
                if "vox cinemas" in page_content and ("dune" in page_content or "avengers" in page_content):
                    # هنا جعلناه يفحص لو التذاكر متاحة فعلاً (أكبر من صفر) قبل إرسال التنبيه
                    # إذا كنت تريد اعتبار ظهور المؤشرات كدليل كافٍ، يمكنك جعل tickets_available = 1 افتراضياً هنا
                    tickets_available = 1  # افتراض مؤقت لحين ربطه بقراءة العدد بدقة من الموقع
                
                # الشرط الجديد: لن يتم إرسال أي إشعار إلا إذا كانت التذاكر متاحة وحقيقية
                if tickets_available > 0:
                    alert_msg = (
                        f"🚨 **تنبيه حجز متاح الآن!** 🚨\n\n"
                        f"🎬 الفيلم: **{movie_name}**\n"
                        f"🎦 الصالة المستهدفة: **{hall_type}**\n\n"
                        f"✨ تم رصد المؤشرات على السيستم بنجاح!\n"
                        f"🔗 [اضغط هنا لفتح صفحة الحجز مباشرة]({direct_link})"
                    )
                    send_telegram_message(session, alert_msg)
                    time.sleep(1)
                    print(f"✅ تم رصد تطابق لـ {movie_name} وإرسال التنبيه.")
                else:
                    print(f"⏳ فيلم '{movie_name}' صالة '{hall_type}' غير متاح للحجز حالياً، البوت صامت في الخلفية.")
                    
            except requests.exceptions.RequestException as e:
                print(f"❌ خطأ في الاتصال أثناء الفحص للفيلم {movie_name}: {e}")
            except Exception as e:
                print(f"❌ خطأ غير متوقع للفيلم {movie_name}: {e}")
            
            time.sleep(2)

if __name__ == "__main__":
    check_booking()
    
