import os
import time
import requests
from bs4 import BeautifulSoup  # مكتبة تحليل صفحات الويب لاستخراج المواعيد

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
        print("✅ تم إرسال التنبيه إلى تليجرام بنجاح!")
    except Exception as e:
        print(f"❌ خطأ في إرسال رسالة تليجرام: {e}")

def check_booking():
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
    }
    
    for target in TARGETS:
        movie_name = target["movie"]
        hall_type = target["hall"]
        query = target["query"]
        direct_link = target["direct_link"]
        search_url = f"https://html.duckduckgo.com/html/?q={query}"
        
        try:
            print(f"⏳ جاري فحص توفر فيلم {movie_name} صالة {hall_type}...")
            response = requests.get(search_url, headers=headers, timeout=15)
            response.raise_for_status()
            
            # استخدام BeautifulSoup لتحليل محتوى الصفحة واستخراج النصوص والنتائج بدقة
            soup = BeautifulSoup(response.text, 'html.parser')
            page_content = response.text.lower()
            
            if "vox cinemas" in page_content and ("dune" in page_content or "avengers" in page_content):
                
                # استخراج اقتباسات أو نصوص من نتائج البحث كمواعيد مقترحة ظاهرة في النتائج
                snippets = [a.get_text() for a in soup.find_all('a', class_='result__snippet')]
                showtimes_found = "\n".join([f"• {s}" for s in snippets[:3]]) if snippets else "مواعيد الحفلات متاحة الآن على السيستم!"

                alert_msg = (
                    f"🚨 **تنبيه حجز متاح الآن!** 🚨\n\n"
                    f"🎬 الفيلم: **{movie_name}**\n"
                    f"🎦 الصالة المستهدفة: **{hall_type}**\n\n"
                    f"⏰ **التفاصيل والمواعيد المرصودة:**\n{showtimes_found}\n\n"
                    f"🔗 [اضغط هنا لفتح صفحة الحجز مباشرة وإتمام الدفع]({direct_link})"
                )
                
                send_telegram_message(alert_msg)
                time.sleep(2)
                print(f"✅ تم رصد تطابق لـ {movie_name} وإرسال التنبيه بالمواعيد.")
            else:
                print(f"⏳ فيلم '{movie_name}' صالة '{hall_type}' لسه غير متاح في النتائج.")
                
        except Exception as e:
            print(f"❌ خطأ أثناء الفحص للفيلم {movie_name}: {e}")
        
        time.sleep(3)

if __name__ == "__main__":
    check_booking()
    
