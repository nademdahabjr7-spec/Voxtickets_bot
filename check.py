import os
import time
import requests
import hashlib

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")

TARGETS = [
    {
        "movie": "Dune Part Three",
        "hall": "IMAX",
        "direct_link": "https://egy.voxcinemas.com/showtimes?c=city-centre-almaza&m=dune-part-three"
    },
    {
        "movie": "Avengers Doomsday",
        "hall": "MAX",
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
    
    with requests.Session() as session:
        session.headers.update(headers)
        
        for target in TARGETS:
            movie_name = target["movie"]
            hall_type = target["hall"]
            target_url = target["direct_link"]
            
            try:
                print(f"⏳ جاري فحص الرابط المباشر لفيلم {movie_name} صالة {hall_type}...")
                response = session.get(target_url, timeout=15)
                response.raise_for_status()
                page_content = response.text.lower()
                
                # حساب بصمة لمحتوى صفحة السينما الرسمية مباشرة
                current_hash = hashlib.md5(page_content.encode('utf-8')).hexdigest()
                
                hash_file = f"hash_{movie_name.replace(' ', '_')}.txt"
                
                previous_hash = ""
                if os.path.exists(hash_file):
                    with open(hash_file, "r") as f:
                        previous_hash = f.read().strip()
                
                if not previous_hash:
                    with open(hash_file, "w") as f:
                        f.write(current_hash)
                    print(f"📌 تم حفظ الحالة الحالية لفيلم {movie_name} كمرجع مباشر، بانتظار التجديد.")
                    continue
                
                # لو محتوى الصفحة اتغير (نزلت حفلات الأسبوع التاني أو التذاكر فتحت)
                if current_hash != previous_hash:
                    alert_msg = (
                        f"🚨 **تنبيه عاجل: تم رصد جدول / تذاكر جديدة!** 🚨\n\n"
                        f"🎬 الفيلم: **{movie_name}**\n"
                        f"🎦 الصالة المستهدفة: **{hall_type}**\n\n"
                        f"✨ موقع السينما قام بتحديث مواعيد الحفلات على الرابط المباشر!\n"
                        f"🔗 [اضغط هنا لفتح الحجز فوراً]({target_url})"
                    )
                    send_telegram_message(session, alert_msg)
                    
                    with open(hash_file, "w") as f:
                        f.write(current_hash)
                        
                    print(f"✅ تم اكتشاف تغيير مباشر في جدول {movie_name} وإرسال التنبيه!")
                else:
                    print(f"⏳ لا يوجد تغيير في صفحة فيلم '{movie_name}' حتى الآن، البوت صامت.")
                    
            except Exception as e:
                print(f"❌ خطأ أثناء فحص الرابط المباشر للفيلم {movie_name}: {e}")
            
            time.sleep(2)

if __name__ == "__main__":
    check_booking()
    
