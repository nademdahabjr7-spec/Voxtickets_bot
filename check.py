import os
import time
import cloudscraper
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

def send_telegram_message(scraper, message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }
    try:
        response = scraper.post(url, json=payload, timeout=15)
        response.raise_for_status()
        print("✅ تم إرسال التنبيه إلى تليجرام بنجاح!")
    except Exception as e:
        print(f"❌ خطأ في إرسال رسالة تليجرام: {e}")

def check_booking():
    # استخدام cloudscraper لتخطي حماية فوكس سينما وسحب الصفحة الحقيقية
    scraper = cloudscraper.create_scraper(
        browser={
            'browser': 'firefox',
            'platform': 'windows',
            'desktop': True
        }
    )
    
    for target in TARGETS:
        movie_name = target["movie"]
        hall_type = target["hall"]
        target_url = target["direct_link"]
        
        try:
            print(f"⏳ جاري فحص الرابط المباشر بذكاء لفيلم {movie_name} صالة {hall_type}...")
            response = scraper.get(target_url, timeout=20)
            response.raise_for_status()
            page_content = response.text.lower()
            
            # حساب بصمة لمحتوى الصفحة الحقيقي
            current_hash = hashlib.md5(page_content.encode('utf-8')).hexdigest()
            hash_file = f"hash_{movie_name.replace(' ', '_')}.txt"
            
            previous_hash = ""
            if os.path.exists(hash_file):
                with open(hash_file, "r") as f:
                    previous_hash = f.read().strip()
            
            if not previous_hash:
                with open(hash_file, "w") as f:
                    f.write(current_hash)
                print(f"📌 تم حفظ الحالة الحالية لفيلم {movie_name} كمرجع، بانتظار التحديث الحقيقي.")
                continue
            
            # لو محتوى جدول السينما اتغير فعلاً (نزلت التذاكر وحفلات جديدة)
            if current_hash != previous_hash:
                alert_msg = (
                    f"🚨 **تنبيه عاجل: تم رصد جدول / تذاكر جديدة!** 🚨\n\n"
                    f"🎬 الفيلم: **{movie_name}**\n"
                    f"🎦 الصالة المستهدفة: **{hall_type}**\n\n"
                    f"✨ تم رصد تحديث فعلي في محتوى صفحة الحجز الرسمية!\n"
                    f"🔗 [اضغط هنا لفتح الحجز فوراً]({target_url})"
                )
                send_telegram_message(scraper, alert_msg)
                
                with open(hash_file, "w") as f:
                    f.write(current_hash)
                    
                print(f"✅ تم اكتشاف تغيير حقيقي وإرسال التنبيه وتحديث البصمة لـ {movie_name}.")
            else:
                print(f"⏳ لا يوجد أي تغيير حقيقي في مواعيد فيلم '{movie_name}' حتى الآن.")
                
        except Exception as e:
            print(f"❌ خطأ أثناء فحص فيلم {movie_name}: {e}")
        
        time.sleep(3)

if __name__ == "__main__":
    check_booking()
    
