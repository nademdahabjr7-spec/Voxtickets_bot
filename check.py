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
        "query": "site:egy.voxcinemas.com/showtimes c=city-centre-almaza dune",
        "direct_link": "https://egy.voxcinemas.com/showtimes?c=city-centre-almaza&m=dune-part-three"
    },
    {
        "movie": "Avengers Doomsday",
        "hall": "MAX",
        "query": "site:egy.voxcinemas.com/showtimes c=city-centre-almaza avengers",
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
            query = target["query"]
            direct_link = target["direct_link"]
            search_url = f"https://html.duckduckgo.com/html/?q={query}"
            
            try:
                print(f"⏳ جاري مراقبة أسبوع جديد لفيلم {movie_name} صالة {hall_type}...")
                response = session.get(search_url, timeout=10)
                response.raise_for_status()
                page_content = response.text.lower()
                
                # استخراج جزء من النص المتعلق بالمواعيد لحساب بصمة له
                # البصمة (Hash) دي بتمثل شكل الصفحة الحالي بالحفلات الحالية
                current_hash = hashlib.md5(page_content.encode('utf-8')).hexdigest()
                
                # ملف محلي لتخزين آخر بصمة تم رصدها لكل فيلم عشان يقارن بيها
                hash_file = f"hash_{movie_name.replace(' ', '_')}.txt"
                
                previous_hash = ""
                if os.path.exists(hash_file):
                    with open(hash_file, "r") as f:
                        previous_hash = f.read().strip()
                
                # لو دي أول مرة يشتغل أو مفيش ملف سابق، نحفظ البصمة الحالية بس من غير تنبيه
                if not previous_hash:
                    with open(hash_file, "w") as f:
                        f.write(current_hash)
                    print(f"📌 تم حفظ الحالة الحالية لفيلم {movie_name} كمرجع، بانتظار أي تغيير جديد.")
                    continue
                
                # الشرط السحري: لو البصمة اتغيرت (يعني الموقع حدث جدوله ونزل الأسبوع التاني)
                if current_hash != previous_hash:
                    alert_msg = (
                        f"🚨 **تنبيه عاجل: تم رصد جدول / تذاكر جديدة!** 🚨\n\n"
                        f"🎬 الفيلم: **{movie_name}**\n"
                        f"🎦 الصالة المستهدفة: **{hall_type}**\n\n"
                        f"✨ موقع السينما قام بتحديث مواعيد الحفلات (احتمال نزول تذاكر الأسبوع الجديد)!\n"
                        f"🔗 [اضغط هنا لفتح الحجز فوراً]({direct_link})"
                    )
                    send_telegram_message(session, alert_msg)
                    
                    # نحدث البصمة المخزنة عشان ميبعتش تاني لنفس التحديث
                    with open(hash_file, "w") as f:
                        f.write(current_hash)
                        
                    print(f"✅ تم اكتشاف تغيير في جدول {movie_name} وإرسال التنبيه وتحديث البصمة.")
                else:
                    print(f"⏳ لا يوجد أي تغيير في مواعيد فيلم '{movie_name}' حتى الآن، البوت صامت.")
                    
            except Exception as e:
                print(f"❌ خطأ أثناء الفحص للفيلم {movie_name}: {e}")
            
            time.sleep(2)

if __name__ == "__main__":
    check_booking()
    
