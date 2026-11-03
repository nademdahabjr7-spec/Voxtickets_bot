import os
import requests

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")

# استخدام الرابط الرئيسي للسينما لتجنب حظر روابط الفروع المؤقتة
TARGET_URL = "https://egy.voxcinemas.com/"

MOVIES_TO_CHECK = ["Dune 3", "Avengers: Doomsday"]


def send_telegram_message(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message, "parse_mode": "Markdown"}
    try:
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        print("✅ تم إرسال التنبيه إلى تليجرام بنجاح!")
    except Exception as e:
        print(f"❌ خطأ في إرسال رسالة تليجرام: {e}")


def check_booking():
    # هيدرز متصفح حقيقي بالكامل لتفادي الحظر أو الـ Timeout
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/123.0.0.0 Safari/537.36"
        ),
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,"
            "image/webp,image/apng,*/*;q=0.8"
        ),
        "Accept-Language": "en-US,en;q=0.9,ar;q=0.8",
        "Connection": "keep-alive",
    }

    try:
        print("⏳ جاري الاتصال بموقع فوكس سينما...")
        response = requests.get(TARGET_URL, headers=headers, timeout=30)
        response.raise_for_status()
        html_content = response.text

        print("✅ تم جلب صفحة الموقع بنجاح، جاري فحص الأفلام...")

        for movie_name in MOVIES_TO_CHECK:
            if movie_name.lower() in html_content.lower():
                alert_msg = (
                    f"🚨 **الحجز فتح يا معلم!** 🚨\n\n"
                    f"فيلم **{movie_name}** متاح دلوقتي.\n\n"
                    f"🔗 [اضغط هنا لزيارة موقع السينما]({TARGET_URL})"
                )
                send_telegram_message(alert_msg)
                print(f"✅ تم رصد الفيلم: {movie_name} وإرسال التنبيه.")
            else:
                print(f"⏳ فيلم '{movie_name}' لسه مش ظاهر في الصفحة الرئيسية.")

    except Exception as e:
        print(f"❌ خطأ أثناء فحص الموقع: {e}")


if __name__ == "__main__":
    check_booking()
    
