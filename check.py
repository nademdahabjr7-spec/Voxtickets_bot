import os
import requests

# جلب البيانات الحساسة من إعدادات GitHub Secrets
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")

# رابط صفحة السينما (ممكن تخليه لرابط فرع معين زي ألماظة لو حابب)
TARGET_URL = "https://eg.voxcinemas.com/showtimes?city-centre-almaza"

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
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9,ar;q=0.8",
    }

    try:
        # رفعنا المهلة لـ 30 ثانية عشان الموقع لو بطيء ما يفصلش
        response = requests.get(TARGET_URL, headers=headers, timeout=30)
        response.raise_for_status()
        html_content = response.text

        for movie_name in MOVIES_TO_CHECK:
            if movie_name.lower() in html_content.lower():
                alert_msg = (
                    f"🚨 **الحجز فتح يا معلم!** 🚨\n\n"
                    f"فيلم **{movie_name}** متاح دلوقتي للبيع/الحجز.\n\n"
                    f"🔗 [اضغط هنا للحجز فوراً]({TARGET_URL})"
                )
                send_telegram_message(alert_msg)
                print(f"✅ تم رصد الفيلم: {movie_name} وإرسال التنبيه.")
            else:
                print(f"⏳ فيلم '{movie_name}' لسه مفيش حجز ليه نازل...")

    except Exception as e:
        print(f"❌ خطأ أثناء فحص الموقع: {e}")


if __name__ == "__main__":
    check_booking()
    
