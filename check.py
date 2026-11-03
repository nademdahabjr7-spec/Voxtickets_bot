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
        "direct_link": "https://egy.voxcinemas.com/showtimes?c=city-centre-almaza&m=dune-part-three",
        "fallback_query": "site:egy.voxcinemas.com/showtimes city-centre-almaza dune imax schedule"
    },
    {
        "movie": "Avengers Doomsday",
        "hall": "MAX",
        "direct_link": "https://egy.voxcinemas.com/showtimes?c=city-centre-almaza&m=avengers-doomsday-infinity-vision",
        "fallback_query": "site:egy.voxcinemas.com/showtimes city-centre-almaza avengers max schedule"
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
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9,ar;q=0.8"
    }
    
    with requests.Session() as session:
        session.headers.update(headers)
        
        for target in TARGETS:
            movie_name = target["movie"]
            hall_type = target["hall"]
            direct_link = target["direct_link"]
            fallback_query = target["fallback_query"]
            
            page_content = ""
            fetched_successfully = False
            
            # المحاولة الأولى: فحص الرابط المباشر للسينما
            try:
                print(f"⏳ محاولة الفحص المباشر لفيلم {movie_name} صالة {hall_type}...")
                response = session.get(direct_link, timeout=12)
                if response.status_code == 200 and len(response.text) > 500:
                    page_content = response.text.lower()
                    fetched_successfully = True
                    print(f"🎯 نجح الفحص المباشر لـ {movie_name} بنجاح!")
            except Exception as e:
                print(f"⚠️ تجاوز حماية الفحص المباشر مؤقتاً لـ {movie_name}, الانتقال لطريقة البحث الاحتياطية...")

            # المحاولة الثانية (الاحتياطية): لو الرابط المباشر جاب Timeout أو حظر، نستخدم محرك البحث الذكي المفلتر
            if not fetched_successfully:
                try:
                    search_url = f"https://html.duckduckgo.com/html/?q={fallback_query}"
                    response = session.get(search_url, timeout=15)
                    response.raise_for_status()
                    page_content = response.text.lower()
                    fetched_successfully = True
                    print(f"🔍 تم الفحص بنجاح عبر نظام البحث الذكي البديل لـ {movie_name}.")
                except Exception as ex:
                    print(f"❌ فشل فحص فيلم {movie_name} بالكامل: {ex}")
                    continue

            if fetched_successfully and page_content:
                current_hash = hashlib.md5(page_content.encode('utf-8')).hexdigest()
                hash_file = f"hash_{movie_name.replace(' ', '_')}.txt"
                
                previous_hash = ""
                if os.path.exists(hash_file):
                    with open(hash_file, "r") as f:
                        previous_hash = f.read().strip()
                
                if not previous_hash:
                    with open(hash_file, "w") as f:
                        f.write(current_hash)
                    print(f"📌 تم حفظ الحالة الأولية لفيلم {movie_name} بنجاح.")
                    continue
                
                if current_hash != previous_hash:
                    alert_msg = (
                        f"🚨 **تنبيه عاجل: تم رصد جدول / تذاكر جديدة!** 🚨\n\n"
                        f"🎬 الفيلم: **{movie_name}**\n"
                        f"🎦 الصالة المستهدفة: **{hall_type}**\n\n"
                        f"✨ تم رصد تحديث حقيقي في مواعيد الحفلات الرسمية!\n"
                        f"🔗 [اضغط هنا لفتح الحجز فوراً]({direct_link})"
                    )
                    send_telegram_message(session, alert_msg)
                    
                    with open(hash_file, "w") as f:
                        f.write(current_hash)
                        
                    print(f"✅ تم رصد تغيير حقيقي وإرسال التنبيه لـ {movie_name}.")
                else:
                    print(f"⏳ لا يوجد أي تغيير جديد في جدول '{movie_name}' حتى الآن.")
                    
            time.sleep(3)

if __name__ == "__main__":
    check_booking()
                    
